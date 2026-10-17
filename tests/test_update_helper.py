import json
import subprocess
import sys
from pathlib import Path

import pytest
from decky_proxy import update_helper as helper


def setup_job(tmp_path):
    plugin = tmp_path / "plugin"
    stage = tmp_path / "stage"
    plugin.mkdir()
    stage.mkdir()
    (plugin / "package.json").write_text('{"version":"0.2.0"}')
    (stage / "package.json").write_text('{"version":"0.2.1"}')
    path = tmp_path / "job.json"
    job = {
        "plugin": str(plugin),
        "stage": str(stage),
        "version": "0.2.1",
        "from_version": "0.2.0",
        "nonce": "a" * 32,
        "phase": "launching",
        "unit": "deckyproxy-update-" + "a" * 32,
    }
    path.write_text(json.dumps(job))
    return path, job


def exchange(first, second):
    temporary = first.with_name("swap-temporary")
    first.rename(temporary)
    second.rename(first)
    temporary.rename(second)


def test_helper_success_requires_matching_health_marker(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)
    monkeypatch.setattr(helper, "exchange", exchange)
    events = []

    def restart():
        events.append("restart")
        (path.parent / "health.json").write_text(
            json.dumps({"version": job["version"], "nonce": job["nonce"]})
        )

    monkeypatch.setattr(helper, "restart_loader", restart)
    helper.perform(path, job, timeout=0.01)
    assert json.loads(path.read_text())["phase"] == "complete"
    assert json.loads((Path(job["plugin"]) / "package.json").read_text())["version"] == "0.2.1"
    assert events == ["restart"]


def test_helper_failed_health_restores_old_tree_and_restarts_once(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)
    monkeypatch.setattr(helper, "exchange", exchange)
    events = []
    monkeypatch.setattr(helper, "restart_loader", lambda: events.append("restart"))
    with pytest.raises(helper.UpdateFailure):
        helper.perform(path, job, timeout=0)
    assert json.loads(path.read_text())["phase"] == "rolled_back"
    assert json.loads((Path(job["plugin"]) / "package.json").read_text())["version"] == "0.2.0"
    assert events == ["restart", "restart"]


def test_helper_recovers_swap_before_phase_was_saved(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)
    exchange(Path(job["plugin"]), Path(job["stage"]))
    monkeypatch.setattr(helper, "exchange", exchange)
    monkeypatch.setattr(helper, "restart_loader", lambda: None)
    (tmp_path / "health.json").write_text(
        json.dumps({"version": job["version"], "nonce": job["nonce"]})
    )
    helper.perform(path, job, timeout=0.01)
    assert json.loads(path.read_text())["phase"] == "complete"


def test_failed_restart_and_wrong_versions_never_lose_old_plugin(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)
    monkeypatch.setattr(helper, "exchange", exchange)
    restarts = []

    def restart():
        restarts.append(1)
        if len(restarts) == 1:
            raise helper.UpdateFailure("restart failed")

    monkeypatch.setattr(helper, "restart_loader", restart)
    with pytest.raises(helper.UpdateFailure):
        helper.perform(path, job, timeout=0)
    assert json.loads(path.read_text())["phase"] == "rolled_back"
    assert restarts == [1, 1]
    (Path(job["stage"]) / "package.json").write_text('{"version":"4.0.0"}')
    with pytest.raises(helper.UpdateFailure, match="版本"):
        helper.perform(path, job)


def test_recovery_completes_interrupted_rollback_without_reinstalling(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)
    exchange(Path(job["plugin"]), Path(job["stage"]))
    monkeypatch.setattr(helper, "exchange", exchange)
    monkeypatch.setattr(helper, "restart_loader", lambda: None)
    helper.perform(path, {**job, "phase": "rolling_back"})
    assert json.loads(path.read_text())["phase"] == "rolled_back"
    assert helper.version_at(Path(job["plugin"])) == "0.2.0"


def test_failed_exchange_leaves_original_tree_and_marks_failed(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)

    def fail(*args):
        raise helper.UpdateFailure("no renameat2")

    monkeypatch.setattr(helper, "exchange", fail)
    with pytest.raises(helper.UpdateFailure):
        helper.perform(path, job, timeout=0)
    assert json.loads(path.read_text())["phase"] == "failed"
    assert helper.version_at(Path(job["plugin"])) == "0.2.0"


def test_corrupt_marker_and_package_are_rejected(tmp_path):
    path, job = setup_job(tmp_path)
    marker = tmp_path / "health.json"
    marker.write_text("{broken")
    assert not helper.healthy(path, job)
    marker.unlink()
    marker.symlink_to(path)
    assert not helper.healthy(path, job)
    (Path(job["plugin"]) / "package.json").write_text("[]")
    with pytest.raises(helper.UpdateFailure):
        helper.version_at(Path(job["plugin"]))
    (Path(job["plugin"]) / "package.json").write_text('{"version":"invalid"}')
    with pytest.raises(helper.UpdateFailure):
        helper.version_at(Path(job["plugin"]))


def test_job_rejects_missing_fields_paths_links_and_wrong_private_owner(tmp_path):
    path, job = setup_job(tmp_path)
    for value in [
        {},
        {**job, "nonce": "../"},
        {**job, "stage": "/etc/stage"},
        {**job, "plugin": "/etc/Other"},
        {**job, "phase": "complete"},
    ]:
        path.write_text(json.dumps(value))
        with pytest.raises(helper.UpdateFailure):
            helper.read_job(path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(helper.UpdateFailure):
        helper.read_job(path)


def test_restart_errors_are_safe_and_bounded(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    for value in [SimpleNamespace(returncode=1), OSError(), subprocess.TimeoutExpired("x", 45)]:

        def run(*args, value=value, **kwargs):
            assert kwargs["timeout"] == 45
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(helper.subprocess, "run", run)
        with pytest.raises(helper.UpdateFailure, match="重启失败"):
            helper.restart_loader()


def test_atomic_exchange_uses_exchange_flag_and_handles_system_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []

    class Rename:
        def __call__(self, *args):
            calls.append(args)
            return 0

    monkeypatch.setattr(
        helper.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(renameat2=Rename())
    )
    helper.exchange(tmp_path / "a", tmp_path / "b")
    assert calls[0][-1] == 2
    monkeypatch.setattr(helper.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    with pytest.raises(helper.UpdateFailure, match="不支持"):
        helper.exchange(tmp_path / "a", tmp_path / "b")


def test_trusted_tree_rejects_links_permissions_types_and_owner(monkeypatch):
    import os
    import stat
    from types import SimpleNamespace

    class FakePath:
        def __init__(self, mode=stat.S_IFDIR | 0o700, uid=0):
            self.mode = mode
            self.uid = uid
            self.parents = []

        def is_absolute(self):
            return True

        def resolve(self):
            return self

        def is_dir(self):
            return True

        def rglob(self, pattern):
            return []

        def lstat(self):
            return SimpleNamespace(st_mode=self.mode, st_uid=self.uid)

    helper.trusted_tree(FakePath())
    for value in [
        FakePath(mode=stat.S_IFDIR | 0o777),
        FakePath(uid=98765),
        FakePath(mode=stat.S_IFLNK | 0o700),
        FakePath(mode=stat.S_IFIFO | 0o600),
    ]:
        with pytest.raises(helper.UpdateFailure):
            helper.trusted_tree(value)
    monkeypatch.setattr(helper.pwd, "getpwnam", lambda value: (_ for _ in ()).throw(KeyError()))
    assert helper.allowed_owners() == {0}
    with pytest.raises(helper.UpdateFailure):
        helper.trusted_tree(FakePath(uid=os.getuid() or 1), private=True)


def test_exchange_fsync_error_after_swap_still_rolls_back(tmp_path, monkeypatch):
    path, job = setup_job(tmp_path)
    calls = []

    def swap(first, second):
        exchange(first, second)
        calls.append(1)
        if len(calls) == 1:
            raise OSError("fsync failed after successful rename")

    monkeypatch.setattr(helper, "exchange", swap)
    monkeypatch.setattr(helper, "restart_loader", lambda: None)
    with pytest.raises(helper.UpdateFailure):
        helper.perform(path, job, timeout=0)
    assert helper.version_at(Path(job["plugin"])) == "0.2.0"
    assert json.loads(path.read_text())["phase"] == "rolled_back"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux renameat2 syscall")
def test_real_linux_atomic_exchange_preserves_both_trees(tmp_path):
    first, second = tmp_path / "live", tmp_path / "staged"
    first.mkdir()
    second.mkdir()
    (first / "version").write_text("old")
    (second / "version").write_text("new")
    helper.exchange(first, second)
    assert (first / "version").read_text() == "new"
    assert (second / "version").read_text() == "old"
    helper.exchange(first, second)
    assert (first / "version").read_text() == "old"
    assert (second / "version").read_text() == "new"


def test_helper_runs_as_standalone_stdlib_script_without_pythonpath():
    result = subprocess.run(
        [sys.executable, helper.__file__],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert result.returncode == 1
    assert result.stderr == b""


def test_standalone_job_requires_exact_nonce_directory_schema_and_upgrade(tmp_path, monkeypatch):
    import os

    nonce = "b" * 32
    plugin = tmp_path / "DeckyProxy"
    stage = tmp_path / nonce / "stage"
    plugin.mkdir()
    stage.mkdir(parents=True)
    (plugin / "package.json").write_text('{"version":"0.2.0"}')
    (stage / "package.json").write_text('{"version":"0.2.1"}')
    path = tmp_path / "job.json"
    job = {
        "plugin": str(plugin),
        "stage": str(stage),
        "version": "0.2.1",
        "from_version": "0.2.0",
        "nonce": nonce,
        "phase": "launching",
        "unit": "deckyproxy-update-" + nonce,
        "error": None,
    }
    original_stat, original_lstat = Path.stat, Path.lstat

    def metadata(original, target, *args, **kwargs):
        value = original(target, *args, **kwargs)
        if target in (path, tmp_path):
            fields = list(value)
            fields[4] = 0
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(
        Path, "stat", lambda target, *a, **kw: metadata(original_stat, target, *a, **kw)
    )
    monkeypatch.setattr(
        Path, "lstat", lambda target, *a, **kw: metadata(original_lstat, target, *a, **kw)
    )
    monkeypatch.setattr(helper, "trusted_tree", lambda *args, **kwargs: None)
    path.write_text(json.dumps(job))
    path.chmod(0o600)
    assert helper.read_job(path) == job
    for bad in [
        {**job, "stage": str(tmp_path / ("c" * 32) / "stage")},
        {**job, "extra": "unexpected"},
        {**job, "version": "00.2.1"},
        {**job, "version": "0.1.0"},
        {**job, "error": []},
    ]:
        path.write_text(json.dumps(bad))
        with pytest.raises(helper.UpdateFailure):
            helper.read_job(path)
