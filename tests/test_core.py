import asyncio
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from decky_proxy.core import Core
from decky_proxy.errors import ProxyError


@pytest.fixture
def core(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "assets").mkdir(parents=True)
    payload = b"\x7fELFtest-core"
    compressed = gzip.compress(payload)
    lock = {
        "version": "v-test",
        "assets": {
            "linux-amd64": {
                "url": "https://example.com/core.gz",
                "sha256": hashlib.sha256(compressed).hexdigest(),
                "unpacked_sha256": hashlib.sha256(payload).hexdigest(),
            }
        },
    }
    (plugin / "assets/core-lock.json").write_text(json.dumps(lock))
    return Core(tmp_path / "runtime", plugin)


def test_missing_lock_is_actionable(tmp_path):
    with pytest.raises(ProxyError):
        Core(tmp_path / "runtime", tmp_path / "missing")


def test_verify_binary_and_detect_modification(core):
    assert not core.installed
    core.binary.parent.mkdir(parents=True)
    core.binary.write_bytes(b"\x7fELFtest-core")
    assert core.installed
    assert core.installed  # cached checksum remains tied to file identity/ctime
    core.binary.write_bytes(b"\x7fELFtampered!")
    assert not core.installed
    core.binary.unlink()
    core.binary.symlink_to("/etc/passwd")
    assert not core.installed


async def test_pinned_install_and_digest_rejection(core, monkeypatch):
    monkeypatch.setattr(Core, "supported", property(lambda self: True))
    monkeypatch.setattr(
        "decky_proxy.core.fetch_https", lambda *a: gzip.compress(b"\x7fELFtest-core", mtime=0)
    )
    with pytest.raises(ProxyError, match="SHA256"):
        await core.install()
    compressed = gzip.compress(b"\x7fELFtest-core", mtime=0)
    core.asset = {**core.asset, "sha256": hashlib.sha256(compressed).hexdigest()}
    await core.install()
    assert core.installed
    assert core.binary.stat().st_mode & 0o777 == 0o700


async def test_install_rejects_wrong_platform_format_and_decompressed_hash(core, monkeypatch):
    monkeypatch.setattr(Core, "supported", property(lambda self: False))
    with pytest.raises(ProxyError):
        await core.install()
    monkeypatch.setattr(Core, "supported", property(lambda self: True))
    for payload, message in [
        (b"broken gzip", "压缩包"),
        (gzip.compress(b"not ELF"), "格式"),
        (gzip.compress(b"\x7fELFother"), "解压"),
    ]:
        monkeypatch.setattr("decky_proxy.core.fetch_https", lambda *a, value=payload: value)
        core.asset = {**core.asset, "sha256": hashlib.sha256(payload).hexdigest()}
        with pytest.raises(ProxyError, match=message):
            await core.install()


class FakeProcess:
    def __init__(self, code=None, timeout=False):
        self.returncode = code
        self.terminated = False
        self.killed = False
        self.timeout = timeout

    async def wait(self):
        if self.timeout and not self.killed:
            raise TimeoutError
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9


async def test_normal_stop_and_timeout_kill_are_reaped(core):
    await core.stop()
    for timeout in [False, True]:
        process = FakeProcess(timeout=timeout)
        core._process = process
        assert core.running
        await core.stop()
        assert process.terminated
        assert process.killed == timeout
        assert not core.running
        assert core._process is None


async def test_validate_handles_nonzero_exit_and_timeout(core, monkeypatch, tmp_path):
    monkeypatch.setattr(core, "_check", lambda: None)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")
    for process in [FakeProcess(0), FakeProcess(1), FakeProcess(timeout=True)]:

        async def spawn(*args, value=process, **kwargs):
            assert kwargs["stdout"] == asyncio.subprocess.DEVNULL
            assert "CLASH_POST_UP" not in kwargs["env"]
            return value

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        if process.returncode == 0:
            await core.validate(config_path)
        else:
            with pytest.raises((ProxyError, TimeoutError)):
                await core.validate(config_path)


async def test_start_uses_argv_parent_guard_and_only_owned_process(core, monkeypatch):
    monkeypatch.setattr(core, "_check", lambda: None)

    async def preflight(path):
        return None

    monkeypatch.setattr(core, "_preflight", preflight)
    monkeypatch.setattr("decky_proxy.core.shutil.which", lambda *a, **k: "/usr/bin/python3")
    core.binary.parent.mkdir(parents=True)
    core.binary.touch()

    async def spawn(*args, **kwargs):
        assert args[0] == "/usr/bin/python3"
        assert args[1].endswith("runner.py")
        assert not kwargs.get("shell")
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await core.start(Path("config"))
    assert core.running
    await core.start(Path("config"))
    await core.stop()


async def test_preflight_port_conflict(core, monkeypatch):
    import socket

    path = core.runtime / "test.json"
    path.write_text('{"tun":{"enable":false}}')
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 19790))
        with pytest.raises(ProxyError, match="19790"):
            await core._preflight(path)


def test_check_rejects_platform_and_unverified_binary(core, monkeypatch):
    monkeypatch.setattr(Core, "supported", property(lambda self: False))
    with pytest.raises(ProxyError):
        core._check()


def test_zip_extracted_binary_gains_execute_bit_before_validation(core, monkeypatch):
    monkeypatch.setattr(Core, "supported", property(lambda self: True))
    core.binary.parent.mkdir(parents=True)
    core.binary.write_bytes(b"\x7fELFtest-core")
    core.binary.chmod(0o644)
    core._check()
    assert core.binary.stat().st_mode & 0o777 == 0o700


async def test_ready_requires_tun_interface_and_route(core, monkeypatch):
    await core.assert_ready(False)
    monkeypatch.setattr(Path, "exists", lambda path: False)
    with pytest.raises(ProxyError, match="接口"):
        await core.assert_ready(True)
    monkeypatch.setattr(Path, "exists", lambda path: True)

    async def routes(*args):
        return []

    monkeypatch.setattr(core, "_ip_json", routes)
    with pytest.raises(ProxyError, match="路由"):
        await core.assert_ready(True)

    async def correct_routes(*args):
        return [{"table": 19792, "dev": "DeckyProxy"}]

    monkeypatch.setattr(core, "_ip_json", correct_routes)
    await core.assert_ready(True)


async def test_ip_command_json_errors_and_reaping(core, monkeypatch):
    monkeypatch.setattr("decky_proxy.core.shutil.which", lambda *a, **k: None)
    with pytest.raises(ProxyError, match="iproute2"):
        await core._ip_json("rule", "show")
    monkeypatch.setattr("decky_proxy.core.shutil.which", lambda *a, **k: "/usr/bin/ip")
    for payload, code, success in [
        (b"[]", 0, True),
        (b"{}", 0, False),
        (b"bad", 0, False),
        (b"[]", 1, False),
    ]:
        process = FakeProcess(code)

        async def communicate(value=payload):
            return value, None

        process.communicate = communicate

        async def spawn(*args, value=process, **kwargs):
            return value

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        if success:
            assert await core._ip_json("rule", "show") == []
        else:
            with pytest.raises(ProxyError):
                await core._ip_json("rule", "show")


def _mock_ip_tables(core, monkeypatch, *, rules=None, routes=None):
    commands = []
    monkeypatch.setattr("decky_proxy.core.shutil.which", lambda *a, **k: "/usr/bin/ip")

    async def spawn(*args, **kwargs):
        commands.append(args)
        process = FakeProcess(0)
        records = rules if "rule" in args else routes

        async def communicate():
            return json.dumps(records or []).encode(), None

        process.communicate = communicate
        return process

    monkeypatch.setattr(core, "_spawn", spawn)
    return commands


async def test_ip_json_requests_numeric_identifiers_and_normalizes_table_numbers(core, monkeypatch):
    routes = [
        {"table": "19792", "dev": "DeckyProxy", "dst": "default"},
        {"table": 254, "dev": "wlan0"},
        {"table": "4294967295", "dev": "other-tun"},
        {"table": "0", "dev": "lo"},
    ]
    commands = _mock_ip_tables(core, monkeypatch, routes=routes)
    result = await core._ip_json("route", "show", "table", "all")
    assert result == [
        {"table": 19792, "dev": "DeckyProxy", "dst": "default"},
        {"table": 254, "dev": "wlan0"},
        {"table": 4294967295, "dev": "other-tun"},
        {"table": 0, "dev": "lo"},
    ]
    assert "-j" in commands[0]
    assert "-N" in commands[0]
    assert commands[0].index("-N") < commands[0].index("route")
    assert routes[0]["table"] == "19792"


@pytest.mark.parametrize("priority", [0, "0", 19793, "19793", 4294967295, "4294967295"])
async def test_ip_json_normalizes_bounded_priority_identifiers(core, monkeypatch, priority):
    rules = [{"table": "19792", "priority": priority, "src": "all"}]
    _mock_ip_tables(core, monkeypatch, rules=rules)
    assert await core._ip_json("rule", "show") == [
        {"table": 19792, "priority": int(priority), "src": "all"}
    ]
    assert rules[0]["priority"] == priority


@pytest.mark.parametrize("member", [None, True, 19792, "19792", []])
async def test_ip_json_rejects_non_record_list_members(core, monkeypatch, member):
    _mock_ip_tables(core, monkeypatch, routes=[{"table": "19792"}, member])
    with pytest.raises(ProxyError, match="无效数据"):
        await core._ip_json("route", "show", "table", "all")


@pytest.mark.parametrize(
    "priority", [None, "", "invalid", True, False, "-1", "4294967296", "１９７９３", 1.5, -1, 2**32]
)
async def test_ip_json_rejects_malformed_priority_before_preflight(core, monkeypatch, priority):
    _mock_ip_tables(core, monkeypatch, rules=[{"table": 254, "priority": priority}])
    with pytest.raises(ProxyError, match="无效数据"):
        await core._ip_json("rule", "show")


@pytest.mark.parametrize(
    "table",
    ["main", "-19792", "4294967296", "１９７９２", "١٩٧٩٢", " 19792", "19792 ", "1" * 10000],
    ids=[
        "name",
        "negative",
        "uint32-overflow",
        "fullwidth",
        "arabic",
        "leading-space",
        "trailing-space",
        "large-name",
    ],
)
async def test_ip_json_preserves_non_numeric_table_names_without_owning_them(
    core, monkeypatch, table
):
    monkeypatch.setattr(Path, "exists", lambda path: True)
    route = {"table": table, "dev": "DeckyProxy"}
    _mock_ip_tables(core, monkeypatch, routes=[route])
    assert await core._ip_json("route", "show", "table", "all") == [route]
    with pytest.raises(ProxyError, match="路由"):
        await core.assert_ready(True)


@pytest.mark.parametrize("table", [19792, "19792"])
async def test_ready_accepts_owned_route_from_actual_ip_json(core, monkeypatch, table):
    monkeypatch.setattr(Path, "exists", lambda path: True)
    _mock_ip_tables(core, monkeypatch, routes=[{"table": table, "dev": "DeckyProxy"}])
    await core.assert_ready(True)


@pytest.mark.parametrize(
    "routes",
    [
        [],
        [{"table": "19792", "dev": "other-tun"}],
        [{"table": "19791", "dev": "DeckyProxy"}],
        [{"table": 254, "dev": "DeckyProxy"}],
        [{"table": "main", "dev": "DeckyProxy"}],
        [{"table": "19792"}],
        [{"dev": "DeckyProxy"}],
        [{"table": "19792", "dev": "DeckyProxy-extra"}],
    ],
)
async def test_ready_rejects_unrelated_or_incomplete_routes(core, monkeypatch, routes):
    monkeypatch.setattr(Path, "exists", lambda path: True)
    _mock_ip_tables(core, monkeypatch, routes=routes)
    with pytest.raises(ProxyError, match="路由"):
        await core.assert_ready(True)


@pytest.mark.parametrize("conflict_source", ["rules", "routes", "priority"])
async def test_preflight_rejects_reserved_table_in_iproute2_string_json(
    core, monkeypatch, conflict_source
):
    config = core.runtime / "tun-preflight.json"
    config.write_text('{"tun":{"enable":true}}')
    original_exists = Path.exists
    monkeypatch.setattr("decky_proxy.core.os.geteuid", lambda: 0)
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: (
            True
            if str(path) == "/dev/net/tun"
            else False
            if str(path) == "/sys/class/net/DeckyProxy"
            else original_exists(path)
        ),
    )
    rules = (
        [{"table": "19792", "priority": 100}]
        if conflict_source == "rules"
        else [{"table": "254", "priority": "19793"}]
        if conflict_source == "priority"
        else []
    )
    routes = [{"table": "19792", "dev": "other-tun"}] if conflict_source == "routes" else []
    _mock_ip_tables(core, monkeypatch, rules=rules, routes=routes)
    with pytest.raises(ProxyError, match="路由表"):
        await core._preflight(config)


async def test_cancel_during_spawn_terminates_owned_child(core, monkeypatch):
    created, release = asyncio.Event(), asyncio.Event()
    process = FakeProcess()

    async def spawn(*args, **kwargs):
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(core._spawn("fake-binary"))
    await created.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert process.returncode is not None
    monkeypatch.setattr(Core, "supported", property(lambda self: True))
    with pytest.raises(ProxyError):
        core._check()
