"""Small, standard-library helpers for reproducible release tooling."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "downloads"


class DownloadSpec(TypedDict):
    """A reviewed upstream artifact pinned to its digest."""

    url: str
    sha256: str


class CoreAsset(DownloadSpec):
    unpacked_sha256: str


class CoreLock(TypedDict):
    version: str
    assets: dict[str, CoreAsset]
    source: DownloadSpec
    pyyaml: DownloadSpec


def sha256_file(path: Path) -> str:
    """Calculate SHA256 without reading an entire core into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_lock() -> CoreLock:
    """Read the checked-in build inputs; never resolve latest releases."""
    with (ROOT / "assets" / "core-lock.json").open(encoding="utf-8") as stream:
        return cast(CoreLock, json.load(stream))


def download_verified(
    spec: DownloadSpec, filename: str, *, maximum_bytes: int = 128 * 1024 * 1024
) -> Path:
    """Cache an HTTPS download only after digest and size validation."""
    if not spec["url"].startswith("https://"):
        raise ValueError("Build inputs must use HTTPS")
    if Path(filename).name != filename:
        raise ValueError("Cache filenames cannot contain directories")
    CACHE.mkdir(parents=True, exist_ok=True)
    destination = CACHE / filename
    if destination.is_file() and sha256_file(destination) == spec["sha256"]:
        return destination

    last_error: Exception | None = None
    for _attempt in range(3):
        temporary: Path | None = None
        try:
            request = urllib.request.Request(
                spec["url"], headers={"User-Agent": "DeckyProxy-release-builder/0.1"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Refusing a redirect to insecure HTTP")
                expected_length = response.headers.get("Content-Length")
                digest = hashlib.sha256()
                size = 0
                with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as output:
                    temporary = Path(output.name)
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > maximum_bytes:
                            raise ValueError(f"Download exceeds {maximum_bytes} bytes")
                        digest.update(chunk)
                        output.write(chunk)
                if expected_length is not None and size != int(expected_length):
                    raise ValueError("Incomplete upstream download")
                if digest.hexdigest() != spec["sha256"]:
                    raise ValueError(f"SHA256 mismatch for {filename}")
            os.replace(temporary, destination)
            return destination
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            ValueError,
        ) as error:
            last_error = error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise RuntimeError(f"Could not obtain verified {filename}: {last_error}") from last_error


def atomic_bytes(path: Path, content: bytes, mode: int = 0o644) -> None:
    """Replace generated build files without leaving a partial artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
