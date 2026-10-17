"""Serialized user operations and transactional running configuration changes."""

import asyncio
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode

from .configuration import build_config, write_provider_files
from .errors import ProxyError
from .maintenance import MaintenanceOperations
from .network import fetch_https
from .profile_files import LocalYamlFiles
from .profile_operations import ProfileOperations
from .storage import Store, atomic_write, private_directory, write_json

READY_ATTEMPTS = 30


class ProxyService(ProfileOperations, MaintenanceOperations):
    def __init__(self, store: Store, runtime: Path, core, controller, secret: str | None = None):
        self.store = store
        self.runtime = runtime
        private_directory(runtime)
        self.core = core
        self.controller = controller
        self.secret = secret or secrets.token_urlsafe(32)
        self.lock = asyncio.Lock()
        self.download = fetch_https
        self.last_error: str | None = None
        self._expected_running = False
        self.updates = None
        self._update_lock = asyncio.Lock()
        self.maintenance_error: str | None = None
        self.files = LocalYamlFiles()

    async def get_status(self) -> dict:
        state = await asyncio.to_thread(self.store.load)
        if self._expected_running and not self.core.running:
            self.last_error = "内核已退出，代理已停止；请检查网络后重新开启"
        return {
            **state,
            "running": self.core.running,
            "core_installed": await asyncio.to_thread(lambda: self.core.installed),
            "core_version": self.core.version,
            "platform_supported": self.core.supported,
            "last_error": self.last_error or self.maintenance_error,
            "mixed_port": 19790,
            "version": "0.2.1",
            "active_profile_summary": await asyncio.to_thread(self.profile_summary, state),
            "update": self.updates.status()
            if self.updates
            else {
                "available": False,
                "version": None,
                "checked_at": None,
                "error": "此环境暂不支持插件更新",
                "state": "idle",
                "supported": False,
            },
        }

    async def _validate(self, state: dict, nodes: dict | list[dict] | None = None) -> Path:
        if not state["active_profile_id"]:
            raise ProxyError("请先导入并选择一个配置")
        if nodes is None:
            nodes = self.store.read_profile(state["active_profile_id"])
        if isinstance(nodes, dict):
            await asyncio.to_thread(write_provider_files, nodes, self.runtime)
        candidate = self.runtime / "candidate.json"
        config = build_config(
            nodes, mode=state["mode"], tun=state["tun_enabled"], secret=self.secret
        )
        await asyncio.to_thread(write_json, candidate, config)
        await self.core.validate(candidate)
        return candidate

    async def _ready(self, tun: bool) -> None:
        last_error = "内核启动超时，已停止代理"
        try:
            async with asyncio.timeout(12):
                for _ in range(READY_ATTEMPTS):
                    if not self.core.running:
                        raise ProxyError("内核启动后退出，请检查端口、TUN 权限与订阅参数")
                    try:
                        await self.controller.request("GET", "/version")
                        actual = await self.controller.request("GET", "/configs")
                        if actual.get("tun", {}).get("enable") is not tun:
                            raise ProxyError("内核 TUN 未就绪，请检查权限和其他代理")
                        await self.core.assert_ready(tun)
                        return
                    except ProxyError as error:
                        last_error = str(error)
                        await asyncio.sleep(0.15)
        except TimeoutError as error:
            raise ProxyError(last_error) from error
        raise ProxyError(last_error)

    async def _apply(self, next_state: dict) -> None:
        if not self.core.running:
            self.store.save(next_state)
            return
        candidate = await self._validate(next_state)
        config = self.runtime / "config.json"
        previous = config.read_bytes()
        previous_state = self.store.load()
        await self.core.stop()
        try:
            atomic_write(config, candidate.read_bytes())
            await self.core.start(config)
            await self._ready(next_state["tun_enabled"])
            self.store.save(next_state)
            self.last_error = None
        except BaseException as error:
            await self.core.stop()
            atomic_write(config, previous)
            self.store.save(previous_state)
            try:
                await self.core.start(config)
                await self._ready(previous_state["tun_enabled"])
            except BaseException as recovery:
                await self.core.stop()
                self._expected_running = False
                self.last_error = "新配置启动失败，旧配置恢复也失败，代理已停止"
                raise ProxyError(self.last_error) from recovery
            raise error

    async def start_proxy(self) -> dict:
        async with self.lock:
            if self.updates and self.updates.status()["state"] == "installing":
                raise ProxyError("插件正在更新，请等待 Decky 重启完成")
            if self.core.running:
                return await self.get_status()
            state = self.store.load()
            candidate = await self._validate(state)
            config = self.runtime / "config.json"
            atomic_write(config, candidate.read_bytes())
            try:
                await self.core.start(config)
                await self._ready(state["tun_enabled"])
            except BaseException:
                await self.core.stop()
                raise
            self._expected_running = True
            self.last_error = None
            return await self.get_status()

    async def stop_proxy(self) -> dict:
        async with self.lock:
            await self.core.stop()
            self._expected_running = False
            self.last_error = None
            return await self.get_status()

    async def set_mode(self, mode: str) -> dict:
        if mode not in ("rule", "global", "direct"):
            raise ProxyError("模式必须为 rule、global 或 direct")
        async with self.lock:
            await self._apply({**self.store.load(), "mode": mode})
            return await self.get_status()

    async def set_tun(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise ProxyError("TUN 设置必须为布尔值")
        async with self.lock:
            await self._apply({**self.store.load(), "tun_enabled": enabled})
            return await self.get_status()

    async def set_auto_start(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise ProxyError("自动启动设置必须为布尔值")
        async with self.lock:
            self.store.save({**self.store.load(), "auto_start": enabled})
            return await self.get_status()

    async def install_core(self) -> dict:
        async with self.lock:
            await self.core.install()
            return await self.get_status()

    async def _groups(self) -> list[dict]:
        if not self.core.running:
            return []
        data = await self.controller.request("GET", "/proxies")
        proxies = data.get("proxies", {})
        groups = []
        for name, value in proxies.items():
            if "all" not in value:
                continue
            options = []
            for option in value["all"]:
                history = proxies.get(option, {}).get("history", [])
                delay = history[-1].get("delay") if history else None
                options.append({"name": option, "delay_ms": delay if delay and delay > 0 else None})
            groups.append(
                {
                    "name": name,
                    "type": value.get("type", ""),
                    "now": value.get("now", ""),
                    "options": options,
                }
            )
        return groups

    async def get_groups(self) -> list[dict]:
        async with self.lock:
            return await self._groups()

    async def select_proxy(self, group: str, proxy: str) -> list[dict]:
        async with self.lock:
            groups = await self._groups()
            match = next(
                (g for g in groups if g["name"] == group and g["type"] == "Selector"), None
            )
            if not match or proxy not in [o["name"] for o in match["options"]]:
                raise ProxyError("策略组或节点无效，请刷新列表；自动选择组无需手动切换")
            await self.controller.request(
                "PUT", "/proxies/" + quote(group, safe=""), {"name": proxy}
            )
            return await self._groups()

    async def test_delay(self, name: str) -> dict:
        async with self.lock:
            groups = await self._groups()
            allowed = {o["name"] for g in groups for o in g["options"]} | {
                g["name"] for g in groups
            }
            if not isinstance(name, str) or name not in allowed:
                raise ProxyError("请先开启代理并选择有效节点")
            query = urlencode({"timeout": 4000, "url": "https://www.gstatic.com/generate_204"})
            data = await self.controller.request(
                "GET", "/proxies/" + quote(name, safe="") + "/delay?" + query
            )
            delay = data.get("delay")
            if type(delay) is not int or delay <= 0:
                raise ProxyError("节点测速超时或不可达")
            return {"delay_ms": delay}

    async def get_diagnostics(self) -> str:
        state = await self.get_status()
        return "\n".join(
            [
                "DeckyProxy 0.2.1",
                f"内核锁定版本：{state['core_version']}",
                f"Linux x86_64：{state['platform_supported']}",
                f"内核校验通过：{state['core_installed']}",
                f"运行：{state['running']} / TUN：{state['tun_enabled']} / 模式：{state['mode']}",
                f"本地代理端口：{state['mixed_port']} / 配置数量：{len(state['profiles'])}",
                "系统 DNS 文件：未修改",
                f"规则：{state['active_profile_summary']}",
                "DNS：IPv4；系统 DNS 劫持需真机确认，不提供 IPv6 代理保证",
                "实机检查：Wi-Fi 切换、待机恢复、UDP、停止后的路由恢复",
            ]
        )
