"""Persistent subscription schedules and update checks, independent of the UI."""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

from .errors import ProxyError
from .storage import write_json


def timestamp(value: object, default: float = 0) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError, OverflowError):
        return default


class MaintenanceOperations:
    """RPC methods mixed into the serialized proxy service."""

    async def set_subscription_interval(self, hours: int) -> dict:
        if type(hours) is not int or hours not in (0, 6, 12, 24):
            raise ProxyError("更新周期必须为关闭、6、12 或 24 小时")
        async with self.lock:
            self.store.save({**self.store.load(), "subscription_interval_hours": hours})
        return await self.get_status()

    async def set_update_preferences(self, auto_check: bool, auto_install: bool) -> dict:
        if type(auto_check) is not bool or type(auto_install) is not bool:
            raise ProxyError("更新开关必须为布尔值")
        if auto_install and not auto_check:
            raise ProxyError("自动安装需要先开启自动检查更新")
        async with self.lock:
            self.store.save(
                {
                    **self.store.load(),
                    "auto_check_updates": auto_check,
                    "auto_install_updates": auto_install,
                }
            )
        return await self.get_status()

    async def check_for_updates(self) -> dict:
        if self.updates is None:
            raise ProxyError("此环境暂不支持插件更新")
        await self.updates.check()
        if (
            not self.updates.status().get("error")
            and self.maintenance_error == "插件更新检查失败，请手动重试"
        ):
            self.maintenance_error = None
        return await self.get_status()

    async def install_update(self, *, automatic: bool = False) -> dict:
        if self.updates is None:
            raise ProxyError("此环境暂不支持插件更新")
        async with self._update_lock:
            async with self.lock:
                if self.core.running:
                    raise ProxyError("请先停止代理，再安装插件更新")
            # Network I/O does not hold the proxy lock. Recheck before launching.
            await self.updates.prepare_install()
            async with self.lock:
                if self.core.running:
                    raise ProxyError("下载期间代理已开启，请停止代理后重试更新")
                state = self.store.load()
                if automatic and not (
                    state["auto_check_updates"] and state["auto_install_updates"]
                ):
                    raise ProxyError("自动安装已关闭，已保留下载的更新包")
                await self.updates.launch_install()
                if self.maintenance_error == "插件自动安装失败，旧版本已保留；请手动重试":
                    self.maintenance_error = None
        return await self.get_status()


class Maintenance:
    def __init__(self, service, *, clock: Callable[[], float] = time.time):
        self.service = service
        self.clock = clock
        self.task: asyncio.Task | None = None
        self.path = service.store.directory / "maintenance.json"
        self.state = self._load()

    def _load(self) -> dict:
        import json

        if not self.path.exists():
            return {"attempts": {}, "update_check": 0, "update_install": 0}
        try:
            if self.path.is_symlink():
                raise ValueError
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("attempts"), dict):
                raise ValueError
            values = [
                *data["attempts"].values(),
                data.get("update_check", 0),
                data.get("update_install", 0),
            ]
            if any(type(value) not in (int, float) or not 0 <= value < 1e12 for value in values):
                raise ValueError
            return data
        except (OSError, ValueError, TypeError) as error:
            raise ProxyError("维护计划文件损坏，请备份设置目录后恢复") from error

    def _save(self, **changes: object) -> None:
        self.state = {**self.state, **changes}
        write_json(self.path, self.state)

    async def tick(self) -> None:
        now = self.clock()
        state = self.service.store.load()
        hours = state["subscription_interval_hours"]
        if hours:
            for meta in state["profiles"]:
                profile = self.service.store.read_profile(meta["id"])
                last = self.state["attempts"].get(meta["id"], timestamp(meta["updated_at"], now))
                if not profile.get("url") or now - last < hours * 3600:
                    continue
                self._save(attempts={**self.state["attempts"], meta["id"]: now})
                message = None
                try:
                    await self.service.refresh_profile(meta["id"])
                except ProxyError:
                    message = "订阅自动更新失败，已保留旧配置；可手动刷新重试"
                await self._record_subscription(now, message)
        if state["auto_check_updates"] and self.service.updates:
            if now - self.state.get("update_check", 0) >= 6 * 3600:
                self._save(update_check=now)
                try:
                    await self.service.check_for_updates()
                except ProxyError:
                    # The updater persists its own safe failure message.
                    self.service.maintenance_error = "插件更新检查失败，请手动重试"
            status = self.service.updates.status()
            state = self.service.store.load()
            if (
                state["auto_install_updates"]
                and status["available"]
                and status["state"] != "installing"
                and not self.service.core.running
                and now - self.state.get("update_install", 0) >= 6 * 3600
            ):
                self._save(update_install=now)
                try:
                    await self.service.install_update(automatic=True)
                except ProxyError:
                    self.service.maintenance_error = "插件自动安装失败，旧版本已保留；请手动重试"

    async def _record_subscription(self, now: float, error: str | None) -> None:
        async with self.service.lock:
            self.service.store.save(
                {
                    **self.service.store.load(),
                    "subscription_last_check": datetime.fromtimestamp(now, UTC).isoformat(),
                    "subscription_error": error,
                }
            )

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="DeckyProxy maintenance")

    async def _run(self) -> None:
        failed = False
        while True:
            try:
                await self.tick()
                if (
                    failed
                    and self.service.maintenance_error == "后台维护失败，请检查设置和网络后重试"
                ):
                    self.service.maintenance_error = None
                failed = False
            except Exception:
                self.service.maintenance_error = "后台维护失败，请检查设置和网络后重试"
                failed = True
            await asyncio.sleep(60)

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
