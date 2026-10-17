"""Decky RPC entry point; secrets stay in the Python backend."""

import asyncio
import secrets
from pathlib import Path

import decky
from decky_proxy.controller import Controller
from decky_proxy.core import Core
from decky_proxy.errors import ProxyError
from decky_proxy.service import ProxyService
from decky_proxy.storage import Store


class Plugin:
    service: ProxyService | None = None

    async def _main(self) -> None:
        secret = secrets.token_urlsafe(32)
        # Decky exposes RUNTIME_DIR through an unauthenticated static asset route.
        # Core configs contain credentials, so keep all backend files in settings.
        settings = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        runtime = settings / "backend"
        self.service = ProxyService(
            Store(settings),
            runtime,
            Core(runtime, Path(decky.DECKY_PLUGIN_DIR)),
            Controller(secret),
            secret,
        )
        if (await self.service.get_status())["auto_start"]:
            try:
                await self.service.start_proxy()
            except Exception as error:
                self.service.last_error = "自动启动失败，请检查网络后手动启动"
                decky.logger.error("DeckyProxy automatic start failed: %s", type(error).__name__)

    async def _unload(self) -> None:
        if self.service:
            await asyncio.shield(self.service.stop_proxy())

    async def _uninstall(self) -> None:
        await self._unload()

    async def _call(self, name: str, *args: object) -> dict:
        if not self.service:
            return {"ok": False, "error": "插件尚未就绪，请稍后重试"}
        try:
            data = await getattr(self.service, name)(*args)
            return {"ok": True, "data": data}
        except ProxyError as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:
            decky.logger.error("DeckyProxy operation %s failed: %s", name, type(error).__name__)
            return {"ok": False, "error": "操作失败，请检查文件权限与网络，然后重试"}

    async def get_status(self) -> dict:
        return await self._call("get_status")

    async def import_profile(self, name: str, url: str, content: str) -> dict:
        return await self._call("import_profile", name, url, content)

    async def refresh_profile(self, profile_id: str) -> dict:
        return await self._call("refresh_profile", profile_id)

    async def activate_profile(self, profile_id: str) -> dict:
        return await self._call("activate_profile", profile_id)

    async def delete_profile(self, profile_id: str) -> dict:
        return await self._call("delete_profile", profile_id)

    async def start_proxy(self) -> dict:
        return await self._call("start_proxy")

    async def stop_proxy(self) -> dict:
        return await self._call("stop_proxy")

    async def set_mode(self, mode: str) -> dict:
        return await self._call("set_mode", mode)

    async def set_tun(self, enabled: bool) -> dict:
        return await self._call("set_tun", enabled)

    async def set_auto_start(self, enabled: bool) -> dict:
        return await self._call("set_auto_start", enabled)

    async def get_groups(self) -> dict:
        return await self._call("get_groups")

    async def select_proxy(self, group: str, proxy: str) -> dict:
        return await self._call("select_proxy", group, proxy)

    async def test_delay(self, name: str) -> dict:
        return await self._call("test_delay", name)

    async def install_core(self) -> dict:
        return await self._call("install_core")

    async def get_diagnostics(self) -> dict:
        return await self._call("get_diagnostics")
