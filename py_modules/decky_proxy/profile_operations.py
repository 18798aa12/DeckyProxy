"""Profile downloads run outside the lifecycle lock; commits retain rollback data."""

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .configuration import prepare_profile, prepare_rule_provider
from .errors import ProxyError
from .network import validate_url
from .profile_cache import prune_provider_cache

MAX_IMPORT_BYTES = 32 * 1024 * 1024
MAX_IMPORT_SECONDS = 120


def budget_download(download: Callable[[str], bytes], cancelled: threading.Event):
    """A cancelled importer cannot keep fetching the rest of a provider graph."""
    used = 0
    deadline = time.monotonic() + MAX_IMPORT_SECONDS

    def bounded(url: str) -> bytes:
        nonlocal used
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise ProxyError("配置下载已取消或超过时间限制")
        data = download(url)
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise ProxyError("配置下载已取消或超过时间限制")
        if not isinstance(data, bytes):
            raise ProxyError("下载内容格式无效")
        used += len(data)
        if used > MAX_IMPORT_BYTES:
            raise ProxyError("订阅及规则集累计下载超过 32 MiB 限制")
        return data

    return bounded


class ProfileOperations:
    def _profile(self, state: dict, profile_id: str) -> dict:
        self.store.profile_path(profile_id)
        for profile in state["profiles"]:
            if profile["id"] == profile_id:
                return profile
        raise ProxyError("配置不存在，请刷新配置列表")

    def profile_summary(self, state: dict) -> dict | None:
        key = state["active_profile_id"]
        if key is None:
            return None
        profile = self.store.read_profile(key)
        return {
            "source_rules": bool(profile.get("source_rules")),
            "rules": len(profile.get("rules") or []),
            "groups": len(profile.get("groups") or []),
            "rule_providers": len(profile.get("rule_providers") or {}),
            "legacy": profile.get("schema_version") != 2,
        }

    async def _content(
        self, url: str, content: str, download: Callable[[str], bytes] | None = None
    ) -> str:
        if not isinstance(url, str) or not isinstance(content, str) or bool(url) == bool(content):
            raise ProxyError("订阅链接和 YAML 文本必须且只能填写其中一项")
        if content:
            return content
        validate_url(url)
        data = await asyncio.to_thread(download or self.download, url)
        try:
            return data.decode("utf-8-sig")
        except UnicodeError as error:
            raise ProxyError("订阅不是 UTF-8 YAML，请检查订阅格式") from error

    async def _import_profile(self, url: str, content: str, custom: list | None = None) -> dict:
        cancelled = threading.Event()
        download = budget_download(self.download, cancelled)
        try:
            async with asyncio.timeout(MAX_IMPORT_SECONDS):
                text = await self._content(url, content, download)
                profile = await asyncio.to_thread(prepare_profile, text, download)
                for source in custom or []:
                    profile = await asyncio.to_thread(
                        prepare_rule_provider,
                        source["name"],
                        source["url"],
                        source["behavior"],
                        source["format"],
                        source["target"],
                        profile,
                        download,
                    )
                return {**profile, "url": url}
        except TimeoutError as error:
            raise ProxyError("订阅及规则集下载超过 120 秒，已保留旧配置，请稍后重试") from error
        finally:
            cancelled.set()

    async def import_profile(self, name: str, url: str, content: str) -> dict:
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise ProxyError("配置名称不能为空，且最多 64 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ProxyError("配置名称不能包含控制字符")
        profile = await self._import_profile(url, content)
        async with self.lock:
            state = self.store.load()
            if len(state["profiles"]) >= 40:
                raise ProxyError("最多保存 40 个订阅，请先删除不需要的配置")
            key = uuid.uuid4().hex
            meta = {
                "id": key,
                "name": name.strip(),
                "updated_at": datetime.now(UTC).isoformat(),
                "source_host": urlsplit(url).hostname if url else None,
            }
            self.store.write_profile(key, profile)
            try:
                self.store.save(
                    {
                        **state,
                        "profiles": [*state["profiles"], meta],
                        "active_profile_id": state["active_profile_id"] or key,
                    }
                )
            except BaseException:
                self.store.delete_profile(key)
                raise
        return await self.get_status()

    async def refresh_profile(self, profile_id: str) -> dict:
        async with self.lock:
            state = self.store.load()
            self._profile(state, profile_id)
            old = self.store.read_profile(profile_id)
            if not old.get("url"):
                # Pasted profiles may still have manually added remote rule sets.
                if not old.get("custom_rule_sources"):
                    raise ProxyError("此配置来自粘贴的 YAML，请重新导入更新版本")
        if old.get("url"):
            profile = await self._import_profile(old["url"], "", old.get("custom_rule_sources"))
        else:
            profile = old
            for source in old["custom_rule_sources"]:
                profile = await asyncio.to_thread(
                    prepare_rule_provider,
                    source["name"],
                    source["url"],
                    source["behavior"],
                    source["format"],
                    source["target"],
                    profile,
                    self.download,
                )
        await self._commit_profile(profile_id, old, profile)
        return await self.get_status()

    async def _commit_profile(self, key: str, old: dict, profile: dict) -> None:
        profile = {**profile, "url": old.get("url", "")}
        async with self.lock:
            state = self.store.load()
            self._profile(state, key)
            if self.store.read_profile(key) != old:
                raise ProxyError("配置在下载期间已更新，请刷新后重试")
            next_state = {
                **state,
                "profiles": [
                    {**p, "updated_at": datetime.now(UTC).isoformat()} if p["id"] == key else p
                    for p in state["profiles"]
                ],
            }
            # Validate before replacing profile data, including when stopped.
            try:
                if self.core.installed:
                    await self._validate({**next_state, "active_profile_id": key}, profile)
                self.store.write_profile(key, profile)
                try:
                    if state["active_profile_id"] == key:
                        await self._apply(next_state)
                    else:
                        self.store.save(next_state)
                except BaseException:
                    self.store.write_profile(key, old)
                    raise
            finally:
                try:
                    await asyncio.to_thread(
                        prune_provider_cache, self.store, self.runtime, self.core.running
                    )
                except (ProxyError, OSError, ValueError):
                    self.maintenance_error = "旧规则缓存清理失败，请检查设置目录权限"

    async def import_rule_provider(
        self, name: str, url: str, behavior: str, format: str, target: str
    ) -> dict:
        async with self.lock:
            state = self.store.load()
            key = state["active_profile_id"]
            if key is None:
                raise ProxyError("请先导入并选择一个配置")
            old = self.store.read_profile(key)
        try:
            async with asyncio.timeout(45):
                profile = await asyncio.to_thread(
                    prepare_rule_provider, name, url, behavior, format, target, old, self.download
                )
        except TimeoutError as error:
            raise ProxyError("规则集下载超时，已保留原配置") from error
        await self._commit_profile(key, old, profile)
        return await self.get_status()

    async def activate_profile(self, profile_id: str) -> dict:
        async with self.lock:
            state = self.store.load()
            self._profile(state, profile_id)
            await self._apply({**state, "active_profile_id": profile_id})
        return await self.get_status()

    async def delete_profile(self, profile_id: str) -> dict:
        async with self.lock:
            state = self.store.load()
            self._profile(state, profile_id)
            if self.core.running and state["active_profile_id"] == profile_id:
                raise ProxyError("请先停止代理，再删除正在使用的配置")
            remaining = [p for p in state["profiles"] if p["id"] != profile_id]
            active = state["active_profile_id"]
            if active == profile_id:
                active = remaining[0]["id"] if remaining else None
            self.store.save({**state, "profiles": remaining, "active_profile_id": active})
            self.store.delete_profile(profile_id)
        return await self.get_status()
