"""Prepare the release-pinned GEO database offline, before core validation."""

import hashlib
import json
import re
from pathlib import Path

from .errors import ProxyError
from .storage import atomic_write


def prepare_geodata(plugin: Path, runtime: Path, config: dict) -> None:
    lock_path = plugin / "assets" / "geodata-lock.json"
    if not lock_path.exists():
        if re.search(r"(?:GEO(?:IP|SITE)|(?:SRC-)?IP-ASN),", json.dumps(config), re.IGNORECASE):
            raise ProxyError("地理规则数据库缺失，请安装完整新版 ZIP")
        return
    try:
        if lock_path.is_symlink():
            raise ValueError
        lock = json.loads(lock_path.read_text())
        for name in ("geoip.dat", "geosite.dat", "ASN.mmdb"):
            digest = lock["files"][name]["sha256"]
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError
            target = runtime / name
            if target.is_symlink():
                raise ValueError
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                continue
            source = plugin / "bin" / "geodata" / name
            if source.is_symlink() or source.parent.is_symlink():
                raise ValueError
            data = source.read_bytes()
            if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError
            atomic_write(target, data)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProxyError("地理规则数据库校验失败，请重新安装完整插件 ZIP") from error
