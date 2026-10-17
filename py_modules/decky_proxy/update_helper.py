"""Standalone systemd transient job: exchange plugin trees and confirm backend health.

This file is copied into the root-private job directory before Decky is restarted.
It intentionally imports only the standard library and never runs a shell command.
"""

import ctypes
import fcntl
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
ACTIVE_PHASES = frozenset({"launching", "swapping", "awaiting_health", "rolling_back"})


class UpdateFailure(Exception):
    """An update failed without including private paths in the user-facing message."""


def save(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".job-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def allowed_owners() -> set[int]:
    try:
        return {0, pwd.getpwnam("deck").pw_uid}
    except KeyError:
        return {0}


def trusted_tree(path: Path, *, private: bool = False) -> None:
    """Reject links and writable plugin files before a root process touches them."""
    if not path.is_absolute() or path.resolve() != path or not path.is_dir():
        raise UpdateFailure("更新目录无效或包含符号链接")
    owners = {0} if private else allowed_owners()
    for entry in [path, *path.rglob("*")]:
        metadata = entry.lstat()
        if (
            metadata.st_uid not in owners
            or metadata.st_mode & 0o022
            or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode))
        ):
            raise UpdateFailure("更新目录所有权、权限或文件类型不安全")
    for parent in path.parents:
        metadata = parent.lstat()
        if metadata.st_uid not in allowed_owners() or metadata.st_mode & 0o022:
            raise UpdateFailure("更新目录父级权限不安全")


def version_at(directory: Path) -> str:
    try:
        value = json.loads((directory / "package.json").read_bytes())["version"]
        if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise ValueError
        return value
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise UpdateFailure("无法读取插件版本") from error


def exchange(first: Path, second: Path) -> None:
    """Linux RENAME_EXCHANGE keeps the plugin path continuously present."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise UpdateFailure("系统不支持原子更新，请手动安装")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(first), -100, os.fsencode(second), 2) != 0:
        raise UpdateFailure("插件目录原子交换失败，当前版本未更改")
    sync_directory(first.parent)
    sync_directory(second.parent)


def restart_loader() -> None:
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "restart", "plugin_loader.service"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            check=False,
            env=ENV,
        )
        if result.returncode:
            raise UpdateFailure("Decky 服务重启失败")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateFailure("Decky 服务重启失败") from error


def healthy(path: Path, job: dict) -> bool:
    try:
        marker = path.parent / "health.json"
        if marker.is_symlink() or not marker.is_file():
            return False
        return json.loads(marker.read_bytes()) == {"version": job["version"], "nonce": job["nonce"]}
    except (OSError, ValueError):
        return False


def perform(path: Path, job: dict, timeout: float = 60) -> None:
    """Reconcile the actual directory versions after interruption, then finish once."""
    plugin, stage = Path(job["plugin"]), Path(job["stage"])
    swapped = version_at(plugin) == job["version"] and version_at(stage) == job["from_version"]
    original = version_at(plugin) == job["from_version"] and version_at(stage) == job["version"]
    if not swapped and not original:
        raise UpdateFailure("更新目录版本不匹配，已停止自动操作")
    if job["phase"] == "rolling_back":
        if swapped:
            exchange(plugin, stage)
        save(path, {**job, "phase": "rolled_back", "error": "更新已恢复到旧版"})
        restart_loader()
        return
    try:
        if original:
            save(path, {**job, "phase": "swapping"})
            exchange(plugin, stage)
            swapped = True
        save(path, {**job, "phase": "awaiting_health"})
        restart_loader()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if healthy(path, job):
                save(path, {**job, "phase": "complete", "error": None})
                return
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        raise UpdateFailure("新版启动确认超时，已恢复旧版")
    except (OSError, UpdateFailure) as error:
        # renameat2 may have succeeded before a directory fsync failed. Inspect
        # the live version instead of assuming the syscall made no change.
        swapped = swapped or version_at(plugin) == job["version"]
        if swapped:
            save(path, {**job, "phase": "rolling_back", "error": "新版启动失败，正在恢复旧版"})
            exchange(plugin, stage)
            save(path, {**job, "phase": "rolled_back", "error": "新版启动失败，已恢复旧版"})
            restart_loader()
        else:
            save(path, {**job, "phase": "failed", "error": "更新未完成，当前版本未更改"})
        raise UpdateFailure("更新未完成，已保留旧版和个人配置") from error


def read_job(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise UpdateFailure("更新任务无效")
    try:
        job = json.loads(path.read_bytes())
        if (
            not isinstance(job, dict)
            or set(job)
            != {"plugin", "stage", "version", "from_version", "nonce", "phase", "unit", "error"}
            or job.get("phase") not in ACTIVE_PHASES
            or not re.fullmatch(r"[a-f0-9]{32}", job.get("nonce", ""))
            or job.get("unit") != "deckyproxy-update-" + job["nonce"]
            or not all(
                isinstance(job.get(key), str)
                for key in ("plugin", "stage", "version", "from_version")
            )
        ):
            raise ValueError
        for key in ("version", "from_version"):
            if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", job[key]):
                raise ValueError
        if tuple(map(int, job["version"].split("."))) <= tuple(
            map(int, job["from_version"].split("."))
        ):
            raise ValueError
        if job["error"] is not None and not isinstance(job["error"], str):
            raise ValueError
        stage = Path(job["stage"])
        if stage != path.parent / job["nonce"] / "stage":
            raise ValueError
        if Path(job["plugin"]).name != "DeckyProxy":
            raise ValueError
        metadata = path.parent.lstat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise UpdateFailure("更新任务目录必须由 root 私有保存")
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
            raise UpdateFailure("更新任务文件权限不安全")
        trusted_tree(Path(job["plugin"]))
        trusted_tree(stage, private=version_at(stage) == job["version"])
        if Path(job["plugin"]).stat().st_dev != stage.stat().st_dev:
            raise UpdateFailure("更新目录位于不同文件系统，请手动安装")
        return job
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise UpdateFailure("更新任务校验失败") from error


def main() -> int:
    if len(sys.argv) != 2 or sys.platform != "linux" or os.geteuid() != 0:
        return 1
    path = Path(sys.argv[1])
    descriptor = None
    try:
        job = read_job(path)
        descriptor = os.open(
            path.parent / ".helper.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise UpdateFailure("更新锁权限无效")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        # The lock owner may have completed while this process was queued.
        job = read_job(path)
        perform(path, job)
    except (UpdateFailure, OSError):
        return 1
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
