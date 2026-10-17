import json

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.service import ProxyService
from decky_proxy.storage import Store

from tests.test_configuration import YAML


class FakeCore:
    running = False
    supported = True
    installed = True
    version = "v1.19.32"
    fail_validate = False
    fail_start = False

    async def validate(self, path):
        if self.fail_validate:
            raise ProxyError("配置校验失败")

    async def start(self, path):
        if self.fail_start:
            raise ProxyError("启动失败")
        self.running = True
        self.config = json.loads(path.read_text())

    async def assert_ready(self, tun):
        if getattr(self, "fail_tun", False):
            raise ProxyError("TUN 接口尚未建立")

    async def stop(self):
        self.running = False

    async def install(self):
        self.installed = True


class FakeController:
    def __init__(self, core):
        self.core = core

    async def request(self, method, path, body=None):
        if path == "/version":
            return {"version": "v1.19.32"}
        if path == "/configs":
            return self.core.config
        if path == "/proxies":
            return {
                "proxies": {
                    "节点选择": {"type": "Selector", "now": "Tokyo", "all": ["Tokyo"]},
                    "Tokyo": {"type": "Trojan", "history": [{"delay": 23}]},
                }
            }
        if "/delay?" in path:
            return {"delay": 23}
        return {}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr("decky_proxy.service.READY_ATTEMPTS", 2)
    core = FakeCore()
    return ProxyService(
        Store(tmp_path / "settings"), tmp_path / "runtime", core, FakeController(core)
    )


async def test_full_import_start_groups_mode_stop_journey(service):
    state = await service.import_profile("机场", "", YAML)
    assert len(state["profiles"]) == 1
    assert state["running"] is False
    assert state["active_profile_id"] == state["profiles"][0]["id"]
    assert (await service.start_proxy())["running"] is True
    groups = await service.get_groups()
    assert groups[0]["options"] == [{"name": "Tokyo", "delay_ms": 23}]
    assert (await service.select_proxy("节点选择", "Tokyo"))[0]["now"] == "Tokyo"
    assert (await service.test_delay("Tokyo"))["delay_ms"] == 23
    assert (await service.set_mode("direct"))["mode"] == "direct"
    assert (await service.set_tun(False))["tun_enabled"] is False
    assert (await service.stop_proxy())["running"] is False


async def test_invalid_import_does_not_destroy_previous_profile(service):
    state = await service.import_profile("first", "", YAML)
    with pytest.raises(ProxyError):
        await service.import_profile("bad", "", "proxies: []")
    assert (await service.get_status())["profiles"] == state["profiles"]


async def test_invalid_config_never_replaces_running_profile(service):
    first = await service.import_profile("first", "", YAML)
    await service.start_proxy()
    second = await service.import_profile("second", "", YAML.replace("Tokyo", "Osaka"))
    service.core.fail_validate = True
    with pytest.raises(ProxyError):
        await service.activate_profile(second["profiles"][1]["id"])
    state = await service.get_status()
    assert state["active_profile_id"] == first["active_profile_id"]
    assert state["running"] is True


async def test_active_profile_cannot_be_deleted_while_running(service):
    state = await service.import_profile("first", "", YAML)
    await service.start_proxy()
    with pytest.raises(ProxyError):
        await service.delete_profile(state["active_profile_id"])
    await service.stop_proxy()
    state = await service.delete_profile(state["active_profile_id"])
    assert state["active_profile_id"] is None


async def test_refresh_is_atomic_and_status_never_leaks_url(service, monkeypatch):
    url = "https://example.com/sub?token=super-secret"
    monkeypatch.setattr(service, "download", lambda url: YAML.encode())
    first = await service.import_profile("airport", url, "")
    key = first["active_profile_id"]
    assert first["profiles"][0]["source_host"] == "example.com"
    assert "super-secret" not in str(first)
    assert "super-secret" not in await service.get_diagnostics()
    monkeypatch.setattr(service, "download", lambda url: b"proxies: []")
    with pytest.raises(ProxyError):
        await service.refresh_profile(key)
    assert service.store.read_profile(key)["nodes"][0]["name"] == "Tokyo"


async def test_provider_materialization_and_name_collision(service, monkeypatch):
    monkeypatch.setattr(service, "download", lambda url: YAML.encode())
    state = await service.import_profile(
        "provider", "", "proxy-providers:\n  p:\n    type: http\n    url: https://example.com/sub\n"
    )
    assert service.store.read_profile(state["active_profile_id"])["nodes"][0]["name"] == "Tokyo"


async def test_inputs_and_autostart_default(service):
    assert (await service.get_status())["auto_start"] is False
    for operation in [
        service.start_proxy(),
        service.set_mode("bad"),
        service.set_tun("true"),
        service.set_auto_start(1),
        service.import_profile("", "", YAML),
        service.import_profile("x", "https://example.com", YAML),
        service.activate_profile("bad"),
    ]:
        with pytest.raises(ProxyError):
            await operation
    await service.set_auto_start(True)
    assert (await service.get_status())["auto_start"] is True
    assert (await service.install_core())["core_installed"] is True


async def test_stopped_group_operations_fail(service):
    assert await service.get_groups() == []
    with pytest.raises(ProxyError):
        await service.select_proxy("x", "y")
    with pytest.raises(ProxyError):
        await service.test_delay("x")


async def test_api_alive_but_tun_failed_is_not_reported_running(service):
    await service.import_profile("first", "", YAML)
    service.core.fail_tun = True
    with pytest.raises(ProxyError, match="TUN"):
        await service.start_proxy()
    assert not (await service.get_status())["running"]


async def test_failed_new_config_start_restores_previous_running_state(service, monkeypatch):
    first = await service.import_profile("first", "", YAML)
    await service.start_proxy()
    second = await service.import_profile("second", "", YAML.replace("Tokyo", "Osaka"))
    original_start = service.core.start
    attempts = []

    async def fail_once(path):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProxyError("测试启动失败")
        await original_start(path)

    monkeypatch.setattr(service.core, "start", fail_once)
    with pytest.raises(ProxyError):
        await service.activate_profile(second["profiles"][1]["id"])
    assert (await service.get_status())["active_profile_id"] == first["active_profile_id"]
    assert service.core.running
    assert service.core.config["proxies"][0]["name"] == "Tokyo"


async def test_refresh_running_profile_succeeds_with_new_nodes(service, monkeypatch):
    monkeypatch.setattr(service, "download", lambda url: YAML.encode())
    initial = await service.import_profile("first", "https://example.com", "")
    await service.start_proxy()
    monkeypatch.setattr(service, "download", lambda url: YAML.replace("Tokyo", "Osaka").encode())
    await service.refresh_profile(initial["active_profile_id"])
    assert service.core.config["proxies"][0]["name"] == "Osaka"


async def test_slow_subscription_does_not_block_stop(service, monkeypatch):
    import asyncio
    import threading

    await service.import_profile("first", "", YAML)
    await service.start_proxy()
    started, release = threading.Event(), threading.Event()

    def download(url):
        started.set()
        release.wait(2)
        return YAML.encode()

    monkeypatch.setattr(service, "download", download)
    pending = asyncio.create_task(service.import_profile("second", "https://example.com/sub", ""))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(service.stop_proxy(), timeout=0.5)
        assert not service.core.running
    finally:
        release.set()
        await pending


async def test_tun_can_become_ready_after_controller_started(service, monkeypatch):
    await service.import_profile("first", "", YAML)
    request = service.controller.request
    observed = []

    async def initially_not_ready(method, path, body=None):
        if path == "/configs":
            observed.append(1)
            if len(observed) == 1:
                return {"tun": {"enable": False}}
        return await request(method, path, body)

    monkeypatch.setattr(service.controller, "request", initially_not_ready)
    assert (await service.start_proxy())["running"]
    assert len(observed) == 2
