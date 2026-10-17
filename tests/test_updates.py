import hashlib
import json
from pathlib import Path

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.updates import UpdateManager

from tests.test_update_manifest import manifest
from tests.test_update_package import package


def manager(tmp_path, monkeypatch):
    plugin = tmp_path / "plugins" / "DeckyProxy"
    plugin.mkdir(parents=True)
    (plugin / "assets").mkdir()
    (plugin / "assets/update-allowed-signers").write_text("public")
    result = UpdateManager(plugin, tmp_path / "runtime", "0.2.0")
    monkeypatch.setattr(result, "_supported", lambda: True)
    return result


async def test_check_only_signed_newer_releases_and_keeps_private_errors(tmp_path, monkeypatch):
    updates = manager(tmp_path, monkeypatch)
    payload = manifest()
    updates.download = lambda url, maximum: b"signed release"
    monkeypatch.setattr("decky_proxy.updates.verify_manifest", lambda *args: payload)
    assert (await updates.check())["available"]
    assert updates.status()["version"] == "0.2.1"
    monkeypatch.setattr("decky_proxy.updates.verify_manifest", lambda *args: manifest("0.1.0"))
    assert not (await updates.check())["available"]
    monkeypatch.setattr(
        "decky_proxy.updates.verify_manifest",
        lambda *args: (_ for _ in ()).throw(ProxyError("bad signature")),
    )
    await updates.check()
    assert updates.status()["error"]
    assert not updates.status()["available"]


async def test_prepare_verifies_size_hash_before_extract_and_persists_job(tmp_path, monkeypatch):
    updates = manager(tmp_path, monkeypatch)
    content = package()
    payload = {**manifest(), "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    updates.download = lambda url, maximum: content
    monkeypatch.setattr("decky_proxy.updates.verify_manifest", lambda *args: payload)
    await updates.check()
    result = await updates.prepare_install()
    assert result["state"] == "available"
    job = json.loads(updates.job_path.read_text())
    assert Path(job["stage"]).is_dir()  # noqa: ASYNC240
    assert job["version"] == "0.2.1"
    assert (Path(job["stage"]) / "package.json").is_file()
    assert not updates.status()["error"]
    assert (await updates.prepare_install())["state"] == "available"


async def test_prepare_corrupt_package_never_replaces_plugin(tmp_path, monkeypatch):
    updates = manager(tmp_path, monkeypatch)
    updates.download = lambda url, maximum: b"corrupt"
    monkeypatch.setattr("decky_proxy.updates.verify_manifest", lambda *args: manifest())
    await updates.check()
    with pytest.raises(ProxyError, match="校验"):
        await updates.prepare_install()
    assert updates.plugin_dir.is_dir()
    assert updates.status()["state"] == "available"


async def test_healthy_marker_only_written_for_expected_version_and_active_job(
    tmp_path, monkeypatch
):
    updates = manager(tmp_path, monkeypatch)
    updates._save_job(
        {
            "plugin": str(updates.plugin_dir),
            "stage": str(updates.directory / ("a" * 32) / "stage"),
            "version": "0.2.1",
            "from_version": "0.2.0",
            "nonce": "a" * 32,
            "phase": "awaiting_health",
            "unit": "deckyproxy-update-" + "a" * 32,
            "error": None,
        }
    )
    updates.mark_healthy()
    assert not updates.health_path.exists()
    next_version = UpdateManager(updates.plugin_dir, updates.runtime, "0.2.1")
    next_version.mark_healthy()
    assert json.loads(updates.health_path.read_text()) == {"version": "0.2.1", "nonce": "a" * 32}
    await next_version.recover()
    assert next_version.status()["state"] == "installing"


def root_permissions(monkeypatch, updates):
    import os

    from decky_proxy import updates as module

    original_stat = Path.stat
    original_lstat = Path.lstat
    job = json.loads(updates.job_path.read_text())
    directory = updates.directory / job["nonce"]
    helper = directory / "helper.py"

    def metadata(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path in (directory, helper):
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result

    def link_metadata(path, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        if path == helper:
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", metadata)
    monkeypatch.setattr(Path, "lstat", link_metadata)
    monkeypatch.setattr(module, "trusted_tree", lambda *args, **kwargs: None)


async def prepared(tmp_path, monkeypatch):
    updates = manager(tmp_path, monkeypatch)
    content = package()
    value = {**manifest(), "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    updates.download = lambda url, maximum: content
    monkeypatch.setattr("decky_proxy.updates.verify_manifest", lambda *args: value)
    await updates.check()
    await updates.prepare_install()
    return updates


async def test_launch_starts_independent_bounded_systemd_unit_and_recover_skips_active(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    updates = await prepared(tmp_path, monkeypatch)
    root_permissions(monkeypatch, updates)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] <= 10
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("decky_proxy.updates.subprocess.run", run)
    assert (await updates.launch_install())["state"] == "installing"
    assert "--property=RuntimeMaxSec=200" in commands[0]
    assert commands[0][0] == "/usr/bin/systemd-run"
    await updates.recover()
    assert commands[-1][:3] == ["/usr/bin/systemctl", "is-active", "--quiet"]
    assert len(commands) == 2


async def test_launch_timeout_keeps_installing_until_recovered(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    updates = await prepared(tmp_path, monkeypatch)
    root_permissions(monkeypatch, updates)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("systemd-run", 10)

    monkeypatch.setattr("decky_proxy.updates.subprocess.run", timeout)
    with pytest.raises(ProxyError, match="待确认"):
        await updates.launch_install()
    assert updates.status()["state"] == "installing"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=3 if command[0].endswith("systemctl") else 0)

    monkeypatch.setattr("decky_proxy.updates.subprocess.run", run)
    await updates.recover()
    assert len(commands) == 2
    assert commands[-1][0] == "/usr/bin/systemd-run"


async def test_unsupported_install_and_corrupt_record_fail_safely(tmp_path, monkeypatch):
    updates = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(updates, "_supported", lambda: False)
    with pytest.raises(ProxyError):
        await updates.prepare_install()
    with pytest.raises(ProxyError):
        await updates.launch_install()
    updates.job_path.write_text("{broken")
    await updates.recover()
    assert updates.status()["error"]
    updates.mark_healthy()
    assert not updates.health_path.exists()


async def test_definitive_launch_failure_keeps_prepared_package_retryable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    updates = await prepared(tmp_path, monkeypatch)
    root_permissions(monkeypatch, updates)
    monkeypatch.setattr(
        "decky_proxy.updates.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    with pytest.raises(ProxyError, match="重试"):
        await updates.launch_install()
    assert updates.status()["state"] == "available"
    assert updates.status()["error"]
    assert json.loads(updates.job_path.read_text())["phase"] == "prepared"
    assert (await updates.prepare_install())["state"] == "available"
    monkeypatch.setattr(
        "decky_proxy.updates.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    assert (await updates.launch_install())["state"] == "installing"
