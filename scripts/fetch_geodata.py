#!/usr/bin/env python3
"""Fetch reproducible GEO database files for offline Steam Deck installation."""

import json
from pathlib import Path

from build_common import ROOT, atomic_bytes, download_verified


def fetch_geodata() -> list[Path]:
    lock = json.loads((ROOT / "assets" / "geodata-lock.json").read_text())
    files = []
    for name in ("geoip.dat", "geosite.dat"):
        spec = lock["files"][name]
        cached = download_verified(spec, f"{spec['sha256']}-{name}", maximum_bytes=32 * 1024 * 1024)
        destination = ROOT / "bin" / "geodata" / name
        atomic_bytes(destination, cached.read_bytes())
        files.append(destination)
    return files


if __name__ == "__main__":
    for path in fetch_geodata():
        print(f"Verified bundled GEO data: {path.name}")
