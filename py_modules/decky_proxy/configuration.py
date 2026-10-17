"""Build managed core settings and expose validated subscription import APIs."""

import copy
import json
import re
from collections.abc import Callable
from pathlib import Path

from .errors import ProxyError
from .network import validate_url
from .profile_protocols import validate_anytls, validate_endpoint, validate_wireguard
from .profile_yaml import load_yaml

MAX_BYTES = 4 * 1024 * 1024
MAX_NODES = 2000
SUPPORTED_TYPES = {
    "ss",
    "ssr",
    "vmess",
    "vless",
    "trojan",
    "hysteria",
    "hysteria2",
    "tuic",
    "socks5",
    "http",
    "anytls",
    "wireguard",
}
RESERVED_NAMES = {"DIRECT", "REJECT", "GLOBAL", "节点选择", "自动选择", "COMPATIBLE", "PASS"}
FORBIDDEN_KEYS = {
    "private-key",
    "private-key-file",
    "private-key-path",
    "client-key",
    "client-certificate",
    "ca",
    "ca-file",
    "certificate",
    "interface-name",
    "routing-mark",
    "smux",
    "dialer-proxy",
}


def _safe_tree(value: object, depth: int = 0, *, wireguard: bool = False) -> None:
    if depth > 12:
        raise ProxyError("节点配置嵌套层级过深")
    if isinstance(value, dict):
        for key, child in value.items():
            if depth == 0 and key == "private-key" and wireguard:
                continue  # Already validated as inline Base64, never a path.
            if depth == 0 and key == "dialer-proxy":
                from .profile_rules import valid_name

                valid_name(child, "链式拨号策略")
                continue
            if not isinstance(key, str) or key.lower() in FORBIDDEN_KEYS:
                raise ProxyError("节点包含不支持的本地文件、接口或链式拨号设置")
            _safe_tree(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _safe_tree(child, depth + 1)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ProxyError("节点包含不支持的数据类型")


def validate_nodes(nodes: object) -> list[dict]:
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise ProxyError("订阅节点列表无效，最多支持 2000 个节点")
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in SUPPORTED_TYPES:
            raise ProxyError("节点协议不支持；请提供常见 Clash/Mihomo 节点订阅")
        name = node.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ProxyError("节点名称为空或过长")
        if name in names or name in RESERVED_NAMES or re.search(r"[\x00-\x1f\x7f]", name):
            raise ProxyError("节点名称重复、含控制字符或与内置策略同名")
        if node["type"] == "wireguard":
            validate_wireguard(node)
        else:
            validate_endpoint(node)
            if node["type"] == "anytls":
                validate_anytls(node)
        _safe_tree(node, wireguard=node["type"] == "wireguard")
        names.add(name)
    return copy.deepcopy(nodes)


def parse_subscription(content: str) -> tuple[list[dict], list[str]]:
    if not isinstance(content, str) or len(content.encode()) > MAX_BYTES:
        raise ProxyError("订阅超过 4 MiB 限制")
    value = load_yaml(content)
    if not isinstance(value, dict):
        raise ProxyError("订阅必须是包含 proxies 的 Clash YAML")
    nodes = validate_nodes(value.get("proxies", []))
    providers = value.get("proxy-providers", {})
    if not isinstance(providers, dict) or len(providers) > 8:
        raise ProxyError("订阅 provider 无效，最多支持 8 个 HTTPS provider")
    urls = []
    for provider in providers.values():
        if not isinstance(provider, dict) or provider.get("type") != "http":
            raise ProxyError("仅支持 HTTPS 节点 provider，不支持本地文件或内联 provider")
        url = provider.get("url")
        validate_url(url)
        urls.append(url)
    if not nodes and not urls:
        raise ProxyError("订阅中没有节点，请使用 Clash/Mihomo YAML 订阅")
    # Catch NaN/Infinity and other data unsupported by the JSON runtime config.
    try:
        json.dumps(nodes, allow_nan=False)
    except ValueError as error:
        raise ProxyError("订阅包含无效数字") from error
    return nodes, urls


def build_config(nodes: list[dict] | dict, *, mode: str, tun: bool, secret: str) -> dict:
    if mode not in ("rule", "global", "direct") or type(tun) is not bool:
        raise ProxyError("代理模式或 TUN 设置无效")
    from .profiles import effective_nodes, effective_rules, runtime_profile

    profile = runtime_profile(nodes) if isinstance(nodes, dict) else None
    validated = validate_nodes(effective_nodes(profile) if profile else nodes)
    if not validated:
        raise ProxyError("请先导入有节点的配置")
    if profile is None:
        from .profile_rules import validate_dialer_graph

        validate_dialer_graph(validated, [], {}, {node["name"] for node in validated})
    names = [node["name"] for node in validated]
    config = {
        "geo-auto-update": False,
        "geodata-mode": True,
        "geodata-loader": "memconservative",
        "mixed-port": 19790,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": mode,
        "log-level": "silent",
        "ipv6": False,
        "external-controller": "127.0.0.1:19791",
        "secret": secret,
        "profile": {"store-selected": True, "store-fake-ip": False},
        "unified-delay": True,
        "tcp-concurrent": True,
        "tun": {
            "enable": tun,
            "device": "DeckyProxy",
            "stack": "mixed",
            "auto-route": True,
            "auto-redirect": False,
            "auto-detect-interface": True,
            "dns-hijack": ["any:53", "tcp://any:53"],
            "strict-route": True,
            "mtu": 1500,
            "iproute2-table-index": 19792,
            "iproute2-rule-index": 19793,
            "route-exclude-address": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        },
        "dns": {
            "enable": True,
            "listen": "127.0.0.1:19792",
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": ["*.lan", "*.local", "+.steamcontent.com", "+.steamserver.net"],
            "default-nameserver": ["223.5.5.5", "1.1.1.1"],
            "nameserver": ["https://dns.alidns.com/dns-query", "https://1.1.1.1/dns-query"],
            "proxy-server-nameserver": ["https://dns.alidns.com/dns-query"],
        },
        "proxies": validated,
        "proxy-groups": [
            {"name": "节点选择", "type": "select", "proxies": ["自动选择", *names, "DIRECT"]},
            {
                "name": "自动选择",
                "type": "url-test",
                "proxies": names,
                "url": "https://www.gstatic.com/generate_204",
                "interval": 600,
                "lazy": True,
                "tolerance": 50,
            },
        ],
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "DOMAIN-SUFFIX,lan,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
            "MATCH,节点选择",
        ],
    }

    if profile:
        config["rules"] = effective_rules(profile)
        if profile["groups"]:
            config["proxies"] = profile["inline_nodes"]
            config["proxy-groups"] = profile["groups"]
            if profile["proxy_providers"]:
                config["proxy-providers"] = profile["proxy_providers"]
        if profile["rule_providers"]:
            config["rule-providers"] = profile["rule_providers"]
    return config


def prepare_profile(content: str, download: Callable[[str], bytes]) -> dict:
    from .profiles import prepare_profile as prepare

    return prepare(content, download)


def prepare_rule_provider(name: str, url: str, behavior: str, format: str, target: str,
                          profile: dict, download: Callable[[str], bytes]) -> dict:
    from .profiles import prepare_rule_provider as prepare

    return prepare(name, url, behavior, format, target, profile, download)


def write_provider_files(profile: dict, runtime: Path) -> None:
    from .profile_providers import write_provider_files as write

    write(profile, runtime)
