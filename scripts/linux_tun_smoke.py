#!/usr/bin/env python3
"""Exercise real TUN lifecycle inside private Linux network/mount namespaces.

Run as root after package.py on Linux x86_64. The synthetic namespace has only
loopback and a dummy uplink, so neither the core nor this check has external
network access. No personal profile or host DNS/routing file is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from decky_proxy.controller import Controller  # noqa: E402
from decky_proxy.core import Core  # noqa: E402
from decky_proxy.service import ProxyService  # noqa: E402
from decky_proxy.storage import Store  # noqa: E402


def executable(name: str) -> str:
    """Use only a system utility, never a repository/PATH replacement."""
    path = shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")
    if path is None:
        raise RuntimeError(f"Required Linux smoke utility is missing: {name}")
    return path


def command(*arguments: str) -> None:
    """Run a bounded setup command; its stderr remains visible on failure."""
    subprocess.run(arguments, check=True, timeout=15)


def namespace_identity(pid: int, namespace: str) -> int:
    """Read a live process' kernel namespace identity."""
    return Path(f"/proc/{pid}/ns/{namespace}").stat().st_ino


def assert_isolated(parent_pid: int) -> None:
    """Refuse mount/link mutations unless both namespaces differ from parent."""
    current_pid = os.getpid()
    if parent_pid <= 1 or parent_pid == current_pid:
        raise RuntimeError("TUN smoke requires isolated network and mount namespaces")
    if any(
        namespace_identity(current_pid, namespace)
        == namespace_identity(parent_pid, namespace)
        for namespace in ("net", "mnt")
    ):
        raise RuntimeError("TUN smoke requires isolated network and mount namespaces")


def synthetic_profile() -> str:
    """A selectable documentation-address node with no remote resources."""
    return json.dumps(
        {
            "proxies": [
                {
                    "name": "Synthetic",
                    "type": "ss",
                    "server": "203.0.113.1",
                    "port": 443,
                    "cipher": "aes-128-gcm",
                    "password": "public-synthetic-smoke-only",
                }
            ],
            "proxy-groups": [
                {"name": "Smoke", "type": "select", "proxies": ["DIRECT", "Synthetic"]}
            ],
            "rules": ["MATCH,DIRECT"],
        }
    )


def no_download(url: str) -> bytes:
    """The smoke importer must never need network resources."""
    raise RuntimeError("Synthetic TUN smoke unexpectedly attempted a download")


async def assert_clean(core: Core) -> None:
    """Wait briefly for real kernel route/rule/interface teardown, then fail."""
    for _ in range(25):
        routes = [
            *(await core._ip_json("route", "show", "table", "all")),
            *(await core._ip_json("-6", "route", "show", "table", "all")),
        ]
        rules = [
            *(await core._ip_json("rule", "show")),
            *(await core._ip_json("-6", "rule", "show")),
        ]
        interface_exists = await asyncio.to_thread(Path("/sys/class/net/DeckyProxy").exists)
        if (
            not core.running
            and not interface_exists
            and not any(route.get("table") == 19792 for route in routes)
            and not any(
                rule.get("table") == 19792 or 19793 <= rule.get("priority", 0) <= 19803
                for rule in rules
            )
        ):
            return
        await asyncio.sleep(0.2)
    raise RuntimeError("Stopping the real core left its TUN interface, routes or rules behind")


async def check_lifecycle() -> None:
    """Use the same profile, service, readiness and cleanup path as the plugin."""
    with tempfile.TemporaryDirectory(prefix="decky-proxy-real-tun-") as temporary:
        directory = Path(temporary)
        runtime = directory / "runtime"
        core = Core(runtime, ROOT)
        secret = "public-synthetic-controller-only"
        controller = Controller(secret)
        service = ProxyService(Store(directory / "settings"), runtime, core, controller, secret)
        service.download = no_download
        try:
            await service.import_profile("Synthetic TUN smoke", "", synthetic_profile())
            await service.set_tun(True)
            status = await service.start_proxy()
            if not status["running"] or not status["tun_enabled"]:
                raise RuntimeError("Real service did not report active TUN")
            await core.assert_ready(True)
            routes = await core._ip_json("route", "show", "table", "all")
            rules = await core._ip_json("rule", "show")
            if not any(
                row.get("table") == 19792 and row.get("dev") == "DeckyProxy" for row in routes
            ) or not any(row.get("table") == 19792 for row in rules):
                raise RuntimeError("Real TUN route table or policy rule was not installed")
            groups = await service.get_groups()
            smoke_group = next((group for group in groups if group["name"] == "Smoke"), None)
            if smoke_group is None or smoke_group["now"] != "DIRECT" or {
                option["name"] for option in smoke_group["options"]
            } != {"DIRECT", "Synthetic"}:
                raise RuntimeError("Real controller did not expose imported group and node")
            actual_rules = await controller.request("GET", "/rules")
            if not any(rule.get("type") == "Match" for rule in actual_rules.get("rules", [])):
                raise RuntimeError("Real controller did not expose the imported MATCH rule")
        finally:
            await service.stop_proxy()
            await assert_clean(core)
    print("Real Linux TUN, table 19792, policy rules, imported groups and stop cleanup passed")


def run_inside(parent_pid: int) -> None:
    """Create namespace-local sysfs and an uplink that cannot leave the namespace."""
    assert_isolated(parent_pid)
    command(executable("mount"), "-t", "sysfs", "-o", "nosuid,nodev,noexec", "sysfs", "/sys")
    if not Path("/dev/net/tun").exists():
        raise RuntimeError("Linux runner has no /dev/net/tun; real TUN validation cannot run")
    ip = executable("ip")
    command(ip, "link", "set", "lo", "up")
    command(ip, "link", "add", "dummy0", "type", "dummy")
    command(ip, "address", "add", "192.0.2.2/24", "dev", "dummy0")
    command(ip, "link", "set", "dummy0", "up")
    command(ip, "route", "add", "default", "via", "192.0.2.1", "dev", "dummy0")
    asyncio.run(check_lifecycle())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace-parent", type=int, help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("Real TUN smoke requires Linux x86_64; no network was changed")
    if os.geteuid() != 0:
        raise SystemExit("Real TUN smoke requires root to create private namespaces")
    if arguments.namespace_parent is not None:
        run_inside(arguments.namespace_parent)
        return
    # The outer process stays alive for the child's isolation checks. No host
    # mount/network mutations occur here. Namespace destruction also cleans up
    # after errors or forced exits, even when the normal core teardown fails.
    process = subprocess.Popen(
        [
            executable("unshare"),
            "--net",
            "--mount",
            "--fork",
            "--propagation",
            "private",
            sys.executable,
            str(Path(__file__).resolve()),
            "--namespace-parent",
            str(os.getpid()),
        ],
        start_new_session=True,
    )
    try:
        result = process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        # Kill the full namespace process group, including a core whose own
        # graceful shutdown might be stuck. Reap unshare before reporting it.
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        raise
    if result != 0:
        raise subprocess.CalledProcessError(result, process.args)


if __name__ == "__main__":
    main()
