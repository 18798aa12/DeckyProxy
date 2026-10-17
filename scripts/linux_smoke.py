#!/usr/bin/env python3
"""Validate the real Linux core without starting a proxy or changing routes."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from build_common import ROOT

sys.path.insert(0, str(ROOT / "py_modules"))

from decky_proxy.configuration import build_config  # noqa: E402


def main() -> None:
    """Run version and config-test commands only on the intended architecture."""
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("This smoke check must run on Linux x86_64; no core was executed")
    binary = ROOT / "bin" / "mihomo"
    subprocess.run([str(binary), "-v"], check=True, timeout=15)
    nodes = [
        {
            "name": "配置检查节点",
            "type": "ss",
            "server": "203.0.113.1",
            "port": 443,
            "cipher": "aes-128-gcm",
            "password": "configuration-test-only",
        }
    ]
    with tempfile.TemporaryDirectory(prefix="decky-proxy-core-check-") as directory:
        config = Path(directory) / "config.json"
        config.write_text(
            json.dumps(build_config(nodes, mode="rule", tun=False, secret="test-only")),
            encoding="utf-8",
        )
        subprocess.run(
            [str(binary), "-t", "-d", directory, "-f", str(config)],
            check=True,
            timeout=30,
        )
    print("Linux core version and generated configuration passed; TUN was not started")


if __name__ == "__main__":
    main()
