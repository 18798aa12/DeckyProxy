#!/usr/bin/env python3
"""Fetch reproducible GEO database files for offline Steam Deck installation."""

import gzip
import hashlib
import io
import json
from pathlib import Path

from build_common import ROOT, atomic_bytes, download_verified


def fetch_geodata() -> list[Path]:
    lock = json.loads((ROOT / "assets" / "geodata-lock.json").read_text())
    files = []
    for name in ("geoip.dat", "geosite.dat", "ASN.mmdb"):
        spec = lock["files"][name]
        compressed = spec.get("compression") == "gzip"
        download = {**spec, "sha256": spec.get("archive_sha256", spec["sha256"])}
        filename = f"{download['sha256']}-{name}" + (".gz" if compressed else "")
        cached = download_verified(download, filename, maximum_bytes=32 * 1024 * 1024)
        content = cached.read_bytes()
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                content = stream.read(32 * 1024 * 1024 + 1)
        if len(content) > 32 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != spec["sha256"]:
            raise ValueError("Expanded GEO data hash or size mismatch")
        destination = ROOT / "bin" / "geodata" / name
        atomic_bytes(destination, content)
        files.append(destination)
    return files


if __name__ == "__main__":
    for path in fetch_geodata():
        print(f"Verified bundled GEO data: {path.name}")
