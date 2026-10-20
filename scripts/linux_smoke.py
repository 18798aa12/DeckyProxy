#!/usr/bin/env python3
"""Check the native core and loopback provider API without TUN or route changes."""

from __future__ import annotations

import base64
import json
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from build_common import ROOT

sys.path.insert(0, str(ROOT / "py_modules"))

from decky_proxy.configuration import (  # noqa: E402
    build_config,
    prepare_profile,
    write_provider_files,
)
from decky_proxy.geodata import prepare_geodata  # noqa: E402


def check_provider_api(binary: Path, config: Path, directory: str, full: dict,
                       expected_groups: dict[str, set[str]]) -> None:
    """Confirm provider loading and actual filtered memberships via the core API."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    full = {
        **full,
        "mixed-port": 0,
        "dns": {"enable": False},
        "external-controller": f"127.0.0.1:{port}",
    }
    config.write_text(json.dumps(full))
    process = subprocess.Popen(
        [str(binary), "-d", directory, "-f", str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        deadline = time.monotonic() + 12
        while True:
            if process.poll() is not None:
                raise ValueError("Core exited before rule providers were ready")
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/providers/rules",
                    headers={"Authorization": "Bearer test-only"},
                )
                with opener.open(request, timeout=1) as response:
                    providers = json.load(response)["providers"]
                if all(
                    providers.get(name, {}).get("ruleCount", 0) > 0
                    for name in ("classical", "inline", "mrs")
                ):
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/proxies",
                        headers={"Authorization": "Bearer test-only"},
                    )
                    with opener.open(request, timeout=1) as response:
                        proxies = json.load(response)["proxies"]
                    if all(set(proxies.get(name, {}).get("all", [])) == expected
                           for name, expected in expected_groups.items()):
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() >= deadline:
                raise ValueError("Rule providers or filtered group memberships failed to load")
            time.sleep(0.1)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def check_core(binary: Path) -> None:
    """Check the selected native core without starting TUN or changing routes."""
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
    nodes = [
        *nodes,
        {
            "name": "AnyTLS-validation",
            "type": "anytls",
            "server": "203.0.113.2",
            "port": 443,
            "password": "configuration-test-only",
            "udp": True,
        },
        {
            "name": "WireGuard-validation",
            "type": "wireguard",
            "server": "203.0.113.3",
            "port": 51820,
            "ip": "10.20.30.2",
            "private-key": base64.b64encode(bytes(range(32))).decode(),
            "public-key": base64.b64encode(bytes(range(1, 33))).decode(),
            "allowed-ips": ["0.0.0.0/0"],
            "udp": True,
        },
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
        # Exercise all provider formats and original routing groups against the
        # actual pinned parser, without opening ports or starting TUN.
        text_rules = Path(directory) / "input.txt"
        text_rules.write_text("+.example.net\n")
        mrs_rules = Path(directory) / "input.mrs"
        subprocess.run(
            [str(binary), "convert-ruleset", "domain", "text", str(text_rules), str(mrs_rules)],
            check=True,
            timeout=15,
        )
        assets = {
            "https://provider.example/nodes": json.dumps(
                {"proxies": [{**nodes[0], "name": name} for name in (
                    "HK-A", "HK-AA", "HK-B", "JP-A", "过期HK-A", "香港-A") ]}
            ).encode(),
            "https://provider.example/rules": b'payload: ["DOMAIN-SUFFIX,example.org"]',
            "https://provider.example/mrs": mrs_rules.read_bytes(),
        }
        profile = prepare_profile(
            json.dumps(
                {
                    "proxies": nodes,
                    "proxy-providers": {
                        "pool": {
                            "type": "http", "url": "https://provider.example/nodes",
                            "filter": "^(?:(?!过期).)*(?:HK|香港|JP)-(?:A|AA|B)$",
                            "exclude-filter": "^(?:HK-B){1}$",
                        }
                    },
                    "proxy-groups": [
                        {
                            "name": "Proxy",
                            "type": "select",
                            "proxies": ["Auto", "DIRECT"],
                            "use": ["pool"],
                        },
                        {"name": "Auto", "type": "url-test", "use": ["pool"],
                         "filter": "(?i)^(?:(?!JP).)*(?:HK|香港)-(?:A|AA)$"},
                        {"name": "Backup", "type": "fallback", "proxies": [nodes[0]["name"]]},
                        {"name": "Balance", "type": "load-balance", "use": ["pool"],
                         "filter": "(?=J)(?=JP)(?=JP-)(?!HK)(?!香港)(?!missing)(?:JP-){1}A$"},
                        {"name": "LongFilter", "type": "select", "use": ["pool"],
                         "filter": "^(?:HK-A|" + "|".join(
                             f"unused-{index:04d}" for index in range(300)) + ")$"},
                    ],
                    "rule-providers": {
                        "classical": {
                            "type": "http",
                            "behavior": "classical",
                            "format": "yaml",
                            "url": "https://provider.example/rules",
                        },
                        "inline": {
                            "type": "inline",
                            "behavior": "domain",
                            "payload": ["+.example.com"],
                        },
                        "mrs": {
                            "type": "http",
                            "behavior": "domain",
                            "format": "mrs",
                            "url": "https://provider.example/mrs",
                        },
                    },
                    "rules": [
                        "RULE-SET,classical,Proxy",
                        "RULE-SET,inline,DIRECT",
                        "RULE-SET,mrs,Proxy",
                        "GEOIP,CN,DIRECT,no-resolve",
                        "GEOSITE,cn,DIRECT",
                        "IP-ASN,13335,DIRECT",
                        "MATCH,Proxy",
                    ],
                }
            ),
            lambda url: assets[url],
        )
        write_provider_files(profile, Path(directory))
        full = build_config(profile, mode="rule", tun=False, secret="test-only")
        prepare_geodata(ROOT, Path(directory), full)
        config.write_text(json.dumps(full), encoding="utf-8")
        subprocess.run(
            [str(binary), "-t", "-d", directory, "-f", str(config)], check=True, timeout=45
        )
        check_provider_api(binary, config, directory, full, {
            "Proxy": {"Auto", "DIRECT", "HK-A", "HK-AA", "JP-A", "香港-A"},
            "Auto": {"HK-A", "HK-AA", "香港-A"},
            "Backup": {nodes[0]["name"]},
            "Balance": {"JP-A"},
            "LongFilter": {"HK-A"},
        })
    print("Native core, filtered groups, providers, MRS and GEO passed; TUN was not started")


def main() -> None:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("This smoke check must run on Linux x86_64; no core was executed")
    check_core(ROOT / "bin" / "mihomo")


if __name__ == "__main__":
    main()
