"""Extract authenticated updates into a new private tree, never over live files."""

import hashlib
import io
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .errors import ProxyError
from .storage import atomic_write
from .update_manifest import MAX_ZIP_BYTES, fsync_directory, version_tuple

MAX_EXPANDED_BYTES = 256 * 1024 * 1024
REQUIRED = (
    "main.py",
    "plugin.json",
    "package.json",
    "dist/index.js",
    "bin/mihomo",
    "assets/core-lock.json",
    "assets/update-allowed-signers",
    "py_modules/decky_proxy/updates.py",
    "py_modules/decky_proxy/update_helper.py",
)
FORBIDDEN = frozenset({"settings", "data", "logs", ".git", ".ssh", ".env", "__pycache__"})


def _member(info: zipfile.ZipInfo) -> tuple[Path, bool]:
    name = info.filename
    path = PurePosixPath(name)
    parts = path.parts
    if (
        not parts
        or parts[0] != "DeckyProxy"
        or path.is_absolute()
        or "\\" in name
        or "\x00" in name
        or any(part in {".", ".."} for part in name.split("/"))
        or any(part in FORBIDDEN or part.startswith(".env.") for part in parts[1:])
        or path.as_posix() != name.rstrip("/")
        or len(name) > 512
    ):
        raise ProxyError("更新包包含不安全的文件路径")
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
        raise ProxyError("更新包不能包含符号链接、设备或加密文件")
    is_directory = info.is_dir()
    if (is_directory and kind == stat.S_IFREG) or (not is_directory and kind == stat.S_IFDIR):
        raise ProxyError("更新包文件类型无效")
    return Path(*parts[1:]), is_directory


def _validate(stage: Path, version: str) -> None:
    if any(not (stage / relative).is_file() for relative in REQUIRED):
        raise ProxyError("更新包缺少必需文件")
    try:
        plugin = json.loads((stage / "plugin.json").read_bytes())
        package = json.loads((stage / "package.json").read_bytes())
        lock = json.loads((stage / "assets/core-lock.json").read_bytes())
        core = (stage / "bin/mihomo").read_bytes()
        if (
            plugin.get("name") != "DeckyProxy"
            or plugin.get("flags") != ["root"]
            or package.get("version") != version
            or not core.startswith(b"\x7fELF\x02\x01")
            or core[18:20] != b"\x3e\x00"
            or hashlib.sha256(core).hexdigest() != lock["assets"]["linux-amd64"]["unpacked_sha256"]
        ):
            raise ValueError
        for source in stage.rglob("*.py"):
            compile(source.read_bytes(), str(source.relative_to(stage)), "exec")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError) as error:
        raise ProxyError("更新包版本、内核或 Python 文件校验失败") from error
    (stage / "bin/mihomo").chmod(0o700)


def extract_release(content: bytes, stage: Path, version: str) -> None:
    """The caller has verified the signature and exact digest of these bytes."""
    version_tuple(version)
    if stage.exists() or stage.is_symlink():
        raise ProxyError("更新暂存目录已存在")
    created = False
    try:
        if not 0 < len(content) <= MAX_ZIP_BYTES:
            raise ProxyError("更新包大小超出限制")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= 3000:
                raise ProxyError("更新包文件数量超出限制")
            if sum(info.file_size for info in members) > MAX_EXPANDED_BYTES:
                raise ProxyError("更新包解压大小超出限制")
            paths = [(_member(info), info) for info in members]
            names = [str(path) for (path, _), _info in paths]
            if len(names) != len(set(names)):
                raise ProxyError("更新包包含重复文件")
            stage.mkdir(mode=0o700)
            created = True
            for (relative, directory), info in paths:
                target = stage / relative
                if directory:
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    if info.file_size > 128 * 1024 * 1024:
                        raise ProxyError("更新包单个文件过大")
                    atomic_write(target, archive.read(info))
            _validate(stage, version)
            for directory in sorted(
                (path for path in stage.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                fsync_directory(directory)
            fsync_directory(stage)
            fsync_directory(stage.parent)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, ProxyError) as error:
        if created:
            shutil.rmtree(stage)
        if isinstance(error, ProxyError):
            raise
        raise ProxyError("更新包解压或校验失败，当前版本未更改") from error
