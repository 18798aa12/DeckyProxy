import hashlib
import json
import subprocess

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.update_manifest import parse_manifest, verify_manifest, version_tuple


def manifest(version="0.2.1"):
    return {
        "schema": 1,
        "version": version,
        "platform": "linux-amd64",
        "url": f"https://github.com/18798aa12/DeckyProxy/releases/download/v{version}/DeckyProxy-{version}.zip",
        "size": 123,
        "sha256": hashlib.sha256(b"package").hexdigest(),
    }


def test_manifest_strict_schema_and_fixed_repository():
    value = manifest()
    assert parse_manifest(json.dumps(value).encode()) == value
    bad = [
        {**value, "url": "https://attacker.example/plugin.zip"},
        {**value, "url": value["url"] + "?secret=x"},
        {**value, "version": "../0.2.1"},
        {**value, "platform": "linux-arm64"},
        {**value, "size": True},
        {**value, "size": 100 * 1024 * 1024},
        {**value, "sha256": "a" * 63},
        {**value, "extra": "unrecognized"},
    ]
    for payload in bad:
        with pytest.raises(ProxyError):
            parse_manifest(json.dumps(payload).encode())
    for payload in [b"{", b"[]", b"x" * 9000, b'{"schema":1,"schema":1}']:
        with pytest.raises(ProxyError):
            parse_manifest(payload)
    assert version_tuple("0.10.0") > version_tuple("0.2.1")
    for version in ["v0.2.1", "0.2", "00.2.1", "0.2.1-beta", "1.2.1000001"]:
        with pytest.raises(ProxyError):
            version_tuple(version)


def test_real_ed25519_signature_and_tamper_rejection(tmp_path):
    key = tmp_path / "key"
    subprocess.run(
        ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
    )
    public = (tmp_path / "key.pub").read_text().split()
    allowed = tmp_path / "allowed"
    allowed.write_text(f"deckyproxy-release {public[0]} {public[1]}\n")
    payload = tmp_path / "manifest.json"
    raw = json.dumps(manifest()).encode()
    payload.write_bytes(raw)
    subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(key),
            "-n",
            "deckyproxy-update",
            str(payload),
        ],
        check=True,
        capture_output=True,
    )
    signature = (tmp_path / "manifest.json.sig").read_bytes()
    assert verify_manifest(raw, signature, allowed, tmp_path) == manifest()
    for data, sig in [(raw + b" ", signature), (raw, b"bad signature")]:
        with pytest.raises(ProxyError, match="签名"):
            verify_manifest(data, sig, allowed, tmp_path)
    allowed.unlink()
    allowed.symlink_to(tmp_path / "key.pub")
    with pytest.raises(ProxyError):
        verify_manifest(raw, signature, allowed, tmp_path)
