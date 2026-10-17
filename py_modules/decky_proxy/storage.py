"""Private, atomic persistence. Profile IDs are never file paths."""

import json
import os
import re
import tempfile
from pathlib import Path

from .errors import ProxyError

DEFAULTS = {
    "mode": "rule",
    "tun_enabled": True,
    "auto_start": False,
    "active_profile_id": None,
    "profiles": [],
    "schema_version": 2,
    "subscription_interval_hours": 0,
    "subscription_last_check": None,
    "subscription_error": None,
    "auto_check_updates": True,
    "auto_install_updates": False,
}


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ProxyError("数据目录不能是符号链接")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        private_directory(directory)

    def load(self) -> dict:
        path = self.directory / "settings.json"
        if not path.exists():
            return {**DEFAULTS, "profiles": []}
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError
            state = {**DEFAULTS, **value}
            if state["mode"] not in ("rule", "global", "direct"):
                raise ValueError
            if any(
                type(state[key]) is not bool
                for key in (
                    "tun_enabled",
                    "auto_start",
                    "auto_check_updates",
                    "auto_install_updates",
                )
            ):
                raise ValueError
            if type(state["subscription_interval_hours"]) is not int or state[
                "subscription_interval_hours"
            ] not in (0, 6, 12, 24):
                raise ValueError
            if state["auto_install_updates"] and not state["auto_check_updates"]:
                raise ValueError
            for key in ("subscription_last_check", "subscription_error"):
                if state[key] is not None and not isinstance(state[key], str):
                    raise ValueError
            state = {**state, "schema_version": 2}
            if not isinstance(state["profiles"], list) or len(state["profiles"]) > 40:
                raise ValueError
            for profile in state["profiles"]:
                self.profile_path(profile["id"])
                if not isinstance(profile["name"], str) or not isinstance(
                    profile["updated_at"], str
                ):
                    raise ValueError
            active = state["active_profile_id"]
            if active is not None and active not in [p["id"] for p in state["profiles"]]:
                raise ValueError
            return state
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ProxyError("设置文件损坏，请先备份 DeckyProxy 设置目录再恢复") from error

    def save(self, state: dict) -> None:
        write_json(self.directory / "settings.json", state)

    def profile_path(self, profile_id: str) -> Path:
        if not isinstance(profile_id, str) or not re.fullmatch(r"[a-f0-9]{32}", profile_id):
            raise ProxyError("配置标识无效")
        return self.directory / "profiles" / f"{profile_id}.json"

    def write_profile(self, profile_id: str, data: dict) -> None:
        write_json(self.profile_path(profile_id), data)

    def read_profile(self, profile_id: str) -> dict:
        path = self.profile_path(profile_id)
        try:
            if path.is_symlink():
                raise ProxyError("配置文件不能是符号链接")
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
                raise ValueError
            return value
        except (OSError, ValueError) as error:
            raise ProxyError("无法读取配置，请重新导入订阅") from error

    def delete_profile(self, profile_id: str) -> None:
        self.profile_path(profile_id).unlink(missing_ok=True)
