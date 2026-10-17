"""Download bounded provider payloads into generated, private file resources."""
import base64
import hashlib
import ipaddress
import json
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from .errors import ProxyError
from .mrs import validate_mrs
from .network import validate_url
from .profile_rules import HEALTH_URL, valid_name, validate_rules
from .profile_yaml import MAX_BYTES, load_yaml
from .storage import atomic_write, private_directory

Download = Callable[[str], bytes]
MAX_PROVIDER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
FILE_PATTERN = re.compile(r"providers/[a-f0-9]{64}\.(?:yaml|text|mrs)")


def fetch_payload(url: object, download: Download) -> bytes:
    validate_url(url)
    payload = download(url)
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BYTES:
        raise ProxyError("远程 provider 为空或超过 4 MiB 限制")
    return payload


def decode_text(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeError as error:
        raise ProxyError("远程 provider 必须是 UTF-8 文本") from error


def file_resource(payload: bytes, format: str) -> tuple[str, str]:
    path = f"providers/{hashlib.sha256(payload).hexdigest()}.{format}"
    return path, base64.b64encode(payload).decode("ascii")


def _mapping(value: object, limit: int) -> dict:
    if not isinstance(value, dict) or len(value) > limit:
        raise ProxyError(f"provider 列表无效，最多支持 {limit} 个 provider")
    for name in value:
        valid_name(name, "provider 名称")
    return value


def proxy_providers(value: object, download: Download) -> tuple[dict, list[dict], dict]:
    from .configuration import validate_nodes

    providers, combined, files = {}, [], {}
    for name, raw in _mapping(value, 8).items():
        if not isinstance(raw, dict):
            raise ProxyError("节点 provider 必须是对象")
        kind = raw.get("type")
        if kind == "http":
            if raw.get("header") or raw.get("headers"):
                raise ProxyError("暂不支持带自定义请求头的节点 provider，请使用 HTTPS 订阅 URL")
            content = load_yaml(decode_text(fetch_payload(raw.get("url"), download)))
            if not isinstance(content, dict) or content.get("proxy-providers"):
                raise ProxyError("节点 provider 必须直接包含 proxies，不支持嵌套 provider")
            nodes = validate_nodes(content.get("proxies"))
        elif kind == "inline":
            nodes = validate_nodes(raw.get("payload"))
        else:
            raise ProxyError("节点 provider 仅支持 HTTPS http 或 inline，不支持本地文件")
        if not nodes:
            raise ProxyError("节点 provider 中没有可用节点")
        payload = json.dumps({"proxies": nodes}, ensure_ascii=False).encode()
        path, encoded = file_resource(payload, "yaml")
        provider = {"type": "file", "path": path}
        health = raw.get("health-check")
        if health is not None:
            if not isinstance(health, dict) or type(health.get("enable", False)) is not bool:
                raise ProxyError("节点 provider 健康检查无效")
            interval = health.get("interval", 600)
            if type(interval) is not int or not 60 <= interval <= 86400:
                raise ProxyError("节点健康检查间隔必须为 60 到 86400 秒")
            provider["health-check"] = {"enable": health.get("enable", False),
                                         "url": HEALTH_URL, "interval": interval}
        providers[name] = provider
        files[path] = encoded
        combined.extend(nodes)
    return providers, validate_nodes(combined), files


def _rule_payload(payload: bytes, behavior: str, format: str) -> bytes:
    if format == "mrs":
        # The system decoder bounds expansion; Mihomo checks strategy semantics.
        if behavior == "classical" or not payload.startswith(b"\x28\xb5\x2f\xfd"):
            raise ProxyError("MRS 仅支持 domain/ipcidr，且必须是有效的 Zstandard 规则文件")
        validate_mrs(payload, behavior)
        return payload
    text = decode_text(payload)
    if format == "yaml":
        value = load_yaml(text)
        if not isinstance(value, dict):
            raise ProxyError("YAML 规则集必须包含 payload 列表")
        entries = value.get("payload")
    else:
        entries = [line.strip() for line in text.splitlines()
                   if line.strip() and not line.lstrip().startswith(("#", "//"))]
    if (not isinstance(entries, list) or not entries or len(entries) > 100_000
            or any(not isinstance(entry, str) or not entry or len(entry) > 4096
                   or re.search(r"[\x00-\x1f\x7f]", entry) for entry in entries)):
        raise ProxyError("规则集必须包含非空字符串规则，最多 100000 条")
    if behavior == "classical":
        validate_rules(entries, set(), set(), classical=True)
    elif behavior == "ipcidr":
        try:
            for entry in entries:
                ipaddress.ip_network(entry, strict=False)
        except ValueError as error:
            raise ProxyError("ipcidr 规则集包含无效网段") from error
    elif any("," in entry or "/" in entry or " " in entry or len(entry) > 253
             for entry in entries):
        raise ProxyError("domain 规则集包含无效域名")
    if format == "yaml":
        # Mihomo's rule-provider reader is line-based, unlike its config loader.
        # It requires block "payload:" syntax, including for inline/flow input.
        return yaml.safe_dump({"payload": entries}, default_flow_style=False,
                              sort_keys=False, allow_unicode=True).encode("utf-8")
    return payload


def rule_providers(value: object, download: Download) -> tuple[dict, dict]:
    providers, files = {}, {}
    for name, raw in _mapping(value, 64).items():
        if not isinstance(raw, dict):
            raise ProxyError("规则 provider 必须是对象")
        kind, behavior, format = raw.get("type"), raw.get("behavior"), raw.get("format", "yaml")
        if (behavior not in ("domain", "ipcidr", "classical")
                or format not in ("yaml", "text", "mrs")):
            raise ProxyError("规则 behavior 或 format 无效")
        if kind == "http":
            if raw.get("header") or raw.get("headers"):
                raise ProxyError("暂不支持带自定义请求头的规则 provider")
            payload = fetch_payload(raw.get("url"), download)
        elif kind == "inline":
            if format != "yaml":
                raise ProxyError("内联规则 provider 仅支持 YAML payload")
            payload = json.dumps({"payload": raw.get("payload")}, ensure_ascii=False).encode()
        else:
            raise ProxyError("规则 provider 仅支持 HTTPS http 或 inline，不支持本地文件")
        payload = _rule_payload(payload, behavior, format)
        path, encoded = file_resource(payload, format)
        providers[name] = {"type": "file", "behavior": behavior, "format": format, "path": path}
        files[path] = encoded
    if sum(len(value) for value in files.values()) > MAX_TOTAL_BYTES:
        raise ProxyError("规则集总大小超过限制")
    return providers, files


def validate_provider_files(files: object) -> dict[str, bytes]:
    if not isinstance(files, dict) or len(files) > 80:
        raise ProxyError("provider 缓存列表无效")
    result = {}
    total = 0
    for path, encoded in files.items():
        if (not isinstance(path, str) or not FILE_PATTERN.fullmatch(path)
                or not isinstance(encoded, str) or len(encoded) > MAX_PROVIDER_BYTES):
            raise ProxyError("provider 缓存路径或大小无效")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise ProxyError("provider 缓存编码无效") from error
        if not payload or hashlib.sha256(payload).hexdigest() != Path(path).stem:
            raise ProxyError("provider 缓存校验失败")
        total += len(payload)
        if total > MAX_TOTAL_BYTES:
            raise ProxyError("provider 缓存总大小超过限制")
        result[path] = payload
    return result


def write_provider_files(profile: dict, runtime: Path) -> None:
    """Only write generated relative hash paths, never subscription paths."""
    files = validate_provider_files(profile.get("provider_files", {}))
    directory = Path(runtime) / "providers"
    private_directory(directory)
    for path, payload in files.items():
        output = Path(runtime) / path
        if output.is_symlink():
            raise ProxyError("provider 缓存文件不能是符号链接")
        atomic_write(output, payload)
