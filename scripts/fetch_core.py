#!/usr/bin/env python3
"""Fetch the locked Steam Deck core and its corresponding upstream source."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

from build_common import ROOT, atomic_bytes, download_verified, load_lock


def fetch_core() -> tuple[Path, Path]:
    """Install a verified Linux amd64 ELF, without executing it on the host."""
    lock = load_lock()
    asset = lock["assets"]["linux-amd64"]
    compressed = download_verified(asset, f"mihomo-linux-amd64-v1-{lock['version']}.gz")
    with gzip.open(compressed, "rb") as stream:
        content = stream.read(128 * 1024 * 1024 + 1)
    if len(content) > 128 * 1024 * 1024:
        raise ValueError("Expanded core exceeds the build size limit")
    if hashlib.sha256(content).hexdigest() != asset["unpacked_sha256"]:
        raise ValueError("Unpacked core SHA256 differs from core-lock.json")
    if content[:6] != b"\x7fELF\x02\x01" or content[18:20] != b"\x3e\x00":
        raise ValueError("Expected a 64-bit little-endian Linux amd64 ELF core")
    binary = ROOT / "bin" / "mihomo"
    atomic_bytes(binary, content, 0o755)
    source = download_verified(
        lock["source"], f"mihomo-{lock['version']}.tar.gz", maximum_bytes=32 * 1024 * 1024
    )
    return binary, source


if __name__ == "__main__":
    binary_path, source_path = fetch_core()
    print(f"Verified Linux core: {binary_path}")
    print(f"Verified corresponding source: {source_path}")
