"""Remove only generated provider files no saved/running profile references."""

import json
from pathlib import Path

from .errors import ProxyError
from .profile_providers import FILE_PATTERN
from .storage import Store


def prune_provider_cache(store: Store, runtime: Path, running: bool) -> None:
    keep = set()
    for meta in store.load()["profiles"]:
        keep.update(store.read_profile(meta["id"]).get("provider_files", {}))
    config = runtime / "config.json"
    if running and config.is_file():
        if config.is_symlink():
            raise ProxyError("运行配置不能是符号链接")
        data = json.loads(config.read_text())
        for key in ("proxy-providers", "rule-providers"):
            keep.update(provider.get("path") for provider in data.get(key, {}).values())
    directory = runtime / "providers"
    if directory.is_symlink():
        raise ProxyError("provider 缓存目录不能是符号链接")
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        relative = "providers/" + path.name
        if FILE_PATTERN.fullmatch(relative) and relative not in keep and not path.is_symlink():
            if path.is_file():
                path.unlink()
