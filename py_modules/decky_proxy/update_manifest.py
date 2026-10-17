"""Only signed releases from the fixed DeckyProxy repository are update candidates."""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .errors import ProxyError
from .network import fetch_https

RELEASE_ROOT = "https://github.com/18798aa12/DeckyProxy/releases/"
MANIFEST_URL = RELEASE_ROOT + "latest/download/update.json"
MAX_ZIP_BYTES = 96 * 1024 * 1024
MIRRORS = ("", "https://ghfast.top/", "https://gh-proxy.org/")
PROCESS_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value
    ):
        raise ProxyError("更新版本号格式无效")
    parts = tuple(int(part) for part in value.split("."))
    if any(part > 1_000_000 for part in parts):
        raise ProxyError("更新版本号超出范围")
    return parts


def _unique(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_manifest(raw: bytes) -> dict:
    try:
        if not raw or len(raw) > 8192:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "version",
            "platform",
            "url",
            "size",
            "sha256",
        }:
            raise ValueError
        version_tuple(value["version"])
        expected = RELEASE_ROOT + f"download/v{value['version']}/DeckyProxy-{value['version']}.zip"
        if (
            type(value["schema"]) is not int
            or value["schema"] != 1
            or value["platform"] != "linux-amd64"
            or value["url"] != expected
            or type(value["size"]) is not int
            or not 0 < value["size"] <= MAX_ZIP_BYTES
            or not isinstance(value["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
        ):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ProxyError("更新清单格式或来源无效") from error


def verify_manifest(raw: bytes, signature: bytes, signers: Path, workdir: Path) -> dict:
    if signers.is_symlink() or not signers.is_file() or len(signature) > 8192:
        raise ProxyError("更新签名公钥缺失或无效")
    try:
        with tempfile.TemporaryDirectory(prefix="verify-", dir=workdir) as temporary:
            path = Path(temporary) / "manifest.sig"
            path.write_bytes(signature)
            path.chmod(0o600)
            result = subprocess.run(
                [
                    "/usr/bin/ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(signers),
                    "-I",
                    "deckyproxy-release",
                    "-n",
                    "deckyproxy-update",
                    "-s",
                    str(path),
                ],
                input=raw,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
                env=PROCESS_ENV,
            )
            if result.returncode != 0:
                raise ProxyError("更新签名验证失败，已拒绝安装")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProxyError("无法验证更新签名，请确认 ssh-keygen 可用") from error
    return parse_manifest(raw)


def download_release(url: str, max_bytes: int) -> bytes:
    """Fallback mirrors transport public release assets only; trust comes from signatures."""
    if url not in (MANIFEST_URL, MANIFEST_URL + ".sig") and not re.fullmatch(
        re.escape(RELEASE_ROOT) + r"download/v\d+\.\d+\.\d+/DeckyProxy-\d+\.\d+\.\d+\.zip", url
    ):
        raise ProxyError("更新下载地址不属于 DeckyProxy 发布仓库")
    for prefix in MIRRORS:
        try:
            return fetch_https(prefix + url, max_bytes)
        except ProxyError:
            continue
    raise ProxyError("无法下载更新，请检查网络后重试；当前版本未更改")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
