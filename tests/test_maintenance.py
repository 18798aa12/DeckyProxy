import asyncio
from datetime import UTC, datetime

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.maintenance import Maintenance


class FakeUpdates:
    def __init__(self):
        self.prepared = 0
        self.launched = 0
        self.checked = 0
        self.value = {
            "available": True,
            "version": "0.3.0",
            "checked_at": None,
            "error": None,
            "state": "available",
            "supported": True,
        }

    def status(self):
        return dict(self.value)

    async def check(self):
        self.checked += 1
        return self.status()

    async def prepare_install(self):
        self.prepared += 1

    async def launch_install(self):
        self.launched += 1
        self.value = {**self.value, "state": "installing"}


async def test_preferences_and_idle_install_guard(service):
    service.updates = FakeUpdates()
    assert (await service.get_status())["auto_check_updates"]
    assert not (await service.get_status())["auto_install_updates"]
    for hours in [True, -1, 1, "6"]:
        with pytest.raises(ProxyError):
            await service.set_subscription_interval(hours)
    for values in [(1, False), (True, "yes"), (False, True)]:
        with pytest.raises(ProxyError):
            await service.set_update_preferences(*values)
    await service.set_subscription_interval(6)
    await service.set_update_preferences(True, True)
    assert (await service.check_for_updates())["update"]["available"]
    service.core.running = True
    with pytest.raises(ProxyError, match="停止"):
        await service.install_update()
    assert service.updates.prepared == 0
    service.core.running = False
    await service.install_update()
    assert service.updates.launched == 1
    with pytest.raises(ProxyError, match="更新"):
        await service.start_proxy()


async def test_scheduler_refreshes_due_urls_only_and_survives_failure(service, monkeypatch):
    from tests.test_configuration import YAML

    service.download = lambda _: YAML.encode()
    first = await service.import_profile("remote", "https://example.com/sub", "")
    await service.import_profile("pasted", "", YAML)
    await service.set_subscription_interval(6)
    await service.set_update_preferences(False, False)
    calls = []

    async def refresh(key):
        calls.append(key)
        raise ProxyError("安全的失败信息")

    monkeypatch.setattr(service, "refresh_profile", refresh)
    now = datetime.now(UTC).timestamp()
    maintenance = Maintenance(service, clock=lambda: now + 7 * 3600)
    await maintenance.tick()
    assert calls == [first["active_profile_id"]]
    assert "失败" in (await service.get_status())["subscription_error"]
    await maintenance.tick()
    assert len(calls) == 1
    # Attempts survive a plugin reload, so a bad subscription is not hammered.
    await Maintenance(service, clock=lambda: now + 7 * 3600).tick()
    assert len(calls) == 1


async def test_scheduler_checks_in_background_and_waits_until_idle(service):
    service.updates = FakeUpdates()
    await service.set_update_preferences(True, True)
    service.core.running = True
    maintenance = Maintenance(service, clock=lambda: 100000)
    await maintenance.tick()
    assert service.updates.checked == 1
    assert service.updates.launched == 0
    service.core.running = False
    await maintenance.tick()
    assert service.updates.launched == 1


async def test_scheduler_cancels_cleanly_without_waiting_for_network(service, monkeypatch):
    started = asyncio.Event()

    async def tick():
        started.set()
        await asyncio.Future()

    maintenance = Maintenance(service)
    monkeypatch.setattr(maintenance, "tick", tick)
    maintenance.start()
    await started.wait()
    await asyncio.wait_for(maintenance.close(), timeout=0.5)
    assert maintenance.task.done()


async def test_disabling_automatic_install_during_download_prevents_restart(service):
    service.updates = FakeUpdates()
    await service.set_update_preferences(True, True)

    async def prepare():
        await service.set_update_preferences(False, False)

    service.updates.prepare_install = prepare
    with pytest.raises(ProxyError, match="关闭"):
        await service.install_update(automatic=True)
    assert service.updates.launched == 0


async def test_disabling_automatic_install_during_check_is_respected(service):
    service.updates = FakeUpdates()
    await service.set_update_preferences(True, True)

    async def check():
        await service.set_update_preferences(False, False)

    service.check_for_updates = check
    await Maintenance(service, clock=lambda: 100000).tick()
    assert service.updates.prepared == 0


async def test_successful_manual_retry_clears_old_background_error(service):
    service.updates = FakeUpdates()
    service.maintenance_error = "插件更新检查失败，请手动重试"
    assert (await service.check_for_updates())["last_error"] is None
    service.maintenance_error = "插件自动安装失败，旧版本已保留；请手动重试"
    assert (await service.install_update())["last_error"] is None


async def test_background_failure_is_visible_and_recovers(service, monkeypatch):
    maintenance = Maintenance(service)
    calls = []
    slept = asyncio.Event()

    async def fail_tick():
        calls.append(True)
        raise OSError("private details should never leak")

    async def sleep(_):
        slept.set()
        await asyncio.Future()

    monkeypatch.setattr(maintenance, "tick", fail_tick)
    monkeypatch.setattr("decky_proxy.maintenance.asyncio.sleep", sleep)
    maintenance.start()
    await slept.wait()
    assert "后台维护" in (await service.get_status())["last_error"]
    await maintenance.close()
