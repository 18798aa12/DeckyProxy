"""Use the installed package as the single source of the plugin version."""

import json
from pathlib import Path

from .errors import ProxyError
from .update_manifest import version_tuple


def package_version(package: Path) -> str:
    """Reject missing or invalid metadata before confirming an update healthy."""
    try:
        value = json.loads(package.read_bytes())["version"]
        version_tuple(value)
        return value
    except (OSError, ValueError, TypeError, KeyError, ProxyError) as error:
        raise ProxyError("插件版本信息缺失或无效，请重新安装完整插件") from error


VERSION = package_version(Path(__file__).resolve().parents[2] / "package.json")
