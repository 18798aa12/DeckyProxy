import importlib
import logging
import sys
from types import SimpleNamespace

import pytest
from decky_proxy.errors import ProxyError


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    decky = SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path / "settings"),
        DECKY_PLUGIN_RUNTIME_DIR=str(tmp_path / "public-data"),
        DECKY_PLUGIN_DIR=str(tmp_path / "plugin"),
        logger=logging.getLogger("test"),
    )
    monkeypatch.setitem(sys.modules, "decky", decky)
    module = importlib.import_module("main")
    monkeypatch.setattr(module, "decky", decky)
    return module, module.Plugin()


async def test_not_ready_and_errors_are_safe(plugin, caplog):
    module, instance = plugin
    assert not (await instance.get_status())["ok"]

    class Service:
        async def get_status(self):
            raise OSError("https://example.com/?token=secret")

    instance.service = Service()
    result = await instance.get_status()
    assert not result["ok"]
    assert "secret" not in str(result) + caplog.text

    async def safe_error():
        raise ProxyError("请先导入订阅")

    instance.service.get_status = safe_error
    assert (await instance.get_status())["error"] == "请先导入订阅"


async def test_every_rpc_matches_backend_contract(plugin):
    _, instance = plugin

    class Service:
        def __getattr__(self, name):
            async def call(*args):
                return {"method": name, "args": args}

            return call

    instance.service = Service()
    calls = {
        "get_status": (),
        "import_profile": ("name", "url", "text"),
        "refresh_profile": ("id",),
        "activate_profile": ("id",),
        "delete_profile": ("id",),
        "start_proxy": (),
        "stop_proxy": (),
        "set_mode": ("rule",),
        "set_tun": (True,),
        "set_auto_start": (False,),
        "get_groups": (),
        "select_proxy": ("group", "node"),
        "test_delay": ("node",),
        "install_core": (),
        "get_diagnostics": (),
        "import_rule_provider": ("rules", "url", "domain", "yaml", "DIRECT"),
        "set_subscription_interval": (6,),
        "set_update_preferences": (True, False),
        "check_for_updates": (),
        "install_update": (),
    }
    for name, args in calls.items():
        assert await getattr(instance, name)(*args) == {
            "ok": True,
            "data": {"method": name, "args": args},
        }


async def test_sensitive_runtime_is_outside_decky_static_data(plugin, monkeypatch):
    from tests.test_service import FakeCore

    module, instance = plugin
    monkeypatch.setattr(module, "Core", lambda *args: FakeCore())
    await instance._main()
    assert instance.service.runtime == instance.service.store.directory / "backend"
    assert not module.Path(module.decky.DECKY_PLUGIN_RUNTIME_DIR).exists()
    assert not (await instance.get_status())["data"]["auto_start"]
    await instance._unload()


async def test_failed_initialization_does_not_mark_update_healthy(plugin, monkeypatch):
    from tests.test_service import FakeCore

    module, instance = plugin
    marked = []

    class Updater:
        def __init__(self, *args):
            pass

        async def recover(self):
            pass

        def mark_healthy(self):
            marked.append(True)

        def status(self):
            return {"state": "idle"}

    def fail_maintenance(service):
        raise ProxyError("维护计划损坏")

    monkeypatch.setattr(module, "Core", lambda *args: FakeCore())
    monkeypatch.setattr(module, "UpdateManager", Updater)
    monkeypatch.setattr(module, "Maintenance", fail_maintenance)
    with pytest.raises(ProxyError):
        await instance._main()
    assert not marked
