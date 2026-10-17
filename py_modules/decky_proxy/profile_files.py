"""Read selected YAML from the user's document folders, never arbitrary root files."""

import os
import pwd
import re
import stat
from pathlib import Path

from .errors import ProxyError

MAX_FILE_BYTES = 4 * 1024 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class LocalYamlFiles:
    def __init__(self, home: Path | None = None, uid: int | None = None):
        if home is None:
            try:
                user = pwd.getpwnam("deck")
                home, uid = Path(user.pw_dir), user.pw_uid
            except KeyError:
                home, uid = Path.home(), os.getuid()
        self.request_home = home.absolute()
        self.home = self.request_home.resolve()
        self.uid = os.getuid() if uid is None else uid

    def _read_relative(self, relative: Path, maximum: int) -> bytes:
        descriptor = os.open(self.home, DIRECTORY_FLAGS)
        try:
            for part in relative.parts[:-1]:
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            child = os.open(relative.name, FILE_FLAGS, dir_fd=descriptor)
            with os.fdopen(child, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise ProxyError("请选择普通 YAML 文件，不能选择目录或特殊文件")
                if metadata.st_uid != self.uid:
                    raise ProxyError("YAML 文件所有者必须是当前用户")
                if metadata.st_size > maximum:
                    raise ProxyError("YAML 文件超过 4 MiB 限制")
                content = stream.read(maximum + 1)
                if len(content) > maximum:
                    raise ProxyError("YAML 文件超过 4 MiB 限制")
                return content
        finally:
            os.close(descriptor)

    def _relative(self, path: Path) -> Path:
        for home in (self.request_home, self.home):
            try:
                relative = path.relative_to(home)
                if relative.parts and not any(part.startswith(".") for part in relative.parts):
                    return relative
            except ValueError:
                continue
        raise ProxyError("请将 YAML 文件放在下载、文档或桌面目录后重新选择")

    def _roots(self) -> tuple[Path, ...]:
        roots = [Path("Downloads"), Path("Documents"), Path("Desktop")]
        try:
            settings = self._read_relative(Path(".config/user-dirs.dirs"), 65536).decode("utf-8")
            configured = []
            for role in ("DOWNLOAD", "DOCUMENTS", "DESKTOP"):
                match = re.search(r"^XDG_" + role + r'_DIR="([^"\r\n]+)"\s*$', settings, re.M)
                if not match:
                    continue
                value = match.group(1)
                candidate = (
                    (self.request_home / value[6:]) if value.startswith("$HOME/") else Path(value)
                )
                if not candidate.is_absolute():
                    continue
                try:
                    configured.append(self._relative(candidate))
                except ProxyError:
                    continue
            return tuple(dict.fromkeys([*configured, *roots]))
        except (OSError, UnicodeError, ProxyError):
            # Missing/unreadable XDG preferences never broaden the fallback folders.
            return tuple(roots)

    def start_directory(self) -> str:
        for relative in self._roots():
            path = self.home / relative
            if path.is_dir() and not path.is_symlink():
                return str(path)
        return str(self.home / "Downloads")

    def read(self, value: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ProxyError("YAML 文件路径无效")
        path = Path(value)
        if not path.is_absolute() or path.suffix.lower() not in (".yaml", ".yml"):
            raise ProxyError("请选择绝对路径的 .yaml 或 .yml 文件")
        relative = self._relative(path)
        if not any(relative.is_relative_to(root) for root in self._roots()):
            raise ProxyError("请将 YAML 文件放在下载、文档或桌面目录后重新选择")
        try:
            data = self._read_relative(relative, MAX_FILE_BYTES)
            return data.decode("utf-8-sig")
        except UnicodeError as error:
            raise ProxyError("YAML 文件必须是 UTF-8 编码") from error
        except OSError as error:
            raise ProxyError(
                "无法读取 YAML 文件，请选择下载目录中的普通文件，不能使用符号链接"
            ) from error
