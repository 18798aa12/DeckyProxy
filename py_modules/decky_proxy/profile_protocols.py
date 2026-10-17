"""Validate inline AnyTLS/WireGuard data without admitting local credentials."""
import base64
import ipaddress
import re

from .errors import ProxyError


def validate_endpoint(node: dict) -> None:
    server, port = node.get("server"), node.get("port")
    if (not isinstance(server, str) or not server or len(server) > 253
            or re.search(r"[\s\x00-\x1f\x7f/\\]", server)):
        raise ProxyError("节点服务器地址无效")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ProxyError("节点端口必须是 1 到 65535 的整数")


def _integer(node: dict, key: str, minimum: int, maximum: int) -> None:
    if key in node and (type(node[key]) is not int or not minimum <= node[key] <= maximum):
        raise ProxyError("节点数值选项无效")


def _booleans(node: dict, keys: tuple[str, ...]) -> None:
    if any(key in node and type(node[key]) is not bool for key in keys):
        raise ProxyError("节点开关必须是布尔值")


def validate_anytls(node: dict) -> None:
    password = node.get("password")
    if (not isinstance(password, str) or not password or len(password) > 4096
            or re.search(r"[\x00-\x1f\x7f]", password)):
        raise ProxyError("AnyTLS 密码为空或格式无效")
    _booleans(node, ("skip-cert-verify", "udp", "disable-reuse"))
    for key in ("idle-session-check-interval", "idle-session-timeout"):
        _integer(node, key, 0, 86400)
    _integer(node, "min-idle-session", 0, 128)
    for key in ("sni", "client-fingerprint", "fingerprint", "name-cert-verify"):
        if key in node and (not isinstance(node[key], str) or len(node[key]) > 1024
                            or re.search(r"[\x00-\x1f\x7f]", node[key])):
            raise ProxyError("AnyTLS TLS 选项无效")
    if "alpn" in node:
        alpn = node["alpn"]
        if (not isinstance(alpn, list) or len(alpn) > 16
                or any(not isinstance(item, str) or not item or len(item) > 255
                       or re.search(r"[\x00-\x1f\x7f]", item) for item in alpn)):
            raise ProxyError("AnyTLS ALPN 列表无效")


def _key(value: object) -> None:
    # Mihomo decodes these values in memory; paths and PEM inputs are rejected.
    if not isinstance(value, str) or len(value) != 44:
        raise ProxyError("WireGuard 密钥必须是内联的 32 字节 Base64 值，不能引用本地文件")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ProxyError("WireGuard 密钥编码无效") from error
    if len(decoded) != 32 or base64.b64encode(decoded).decode() != value:
        raise ProxyError("WireGuard 密钥长度或编码无效")


def _reserved(node: dict) -> None:
    if "reserved" not in node:
        return
    reserved = node["reserved"]
    if (not isinstance(reserved, list) or len(reserved) != 3
            or any(type(item) is not int or not 0 <= item <= 255 for item in reserved)):
        raise ProxyError("WireGuard reserved 必须包含 3 个字节")


def _allowed_ips(node: dict, *, required: bool) -> None:
    if not required and "allowed-ips" not in node:
        return
    addresses = node.get("allowed-ips")
    if not isinstance(addresses, list) or not addresses or len(addresses) > 256:
        raise ProxyError("WireGuard allowed-ips 列表无效")
    try:
        for address in addresses:
            if not isinstance(address, str) or "/" not in address:
                raise ValueError
            ipaddress.ip_network(address, strict=False)
    except ValueError as error:
        raise ProxyError("WireGuard allowed-ips 包含无效网段") from error


def _peer(node: dict, *, explicit: bool) -> None:
    if explicit and set(node) - {
            "server", "port", "public-key", "pre-shared-key", "reserved", "allowed-ips"}:
        raise ProxyError("WireGuard peer 包含不支持的字段")
    validate_endpoint(node)
    _key(node.get("public-key"))
    if "pre-shared-key" in node:
        _key(node["pre-shared-key"])
    _reserved(node)
    _allowed_ips(node, required=explicit)


def validate_wireguard(node: dict) -> None:
    _key(node.get("private-key"))
    if not node.get("ip") and not node.get("ipv6"):
        raise ProxyError("WireGuard 至少需要一个本地 IP 地址")
    try:
        for key, version in (("ip", 4), ("ipv6", 6)):
            if key in node:
                address = node[key]
                if (not isinstance(address, str)
                        or ipaddress.ip_interface(address).version != version):
                    raise ValueError
    except ValueError as error:
        raise ProxyError("WireGuard 本地 IP 地址无效") from error
    peers = node.get("peers")
    if peers is not None:
        if (not isinstance(peers, list) or not peers or len(peers) > 32
                or any(not isinstance(peer, dict) for peer in peers)):
            raise ProxyError("WireGuard peers 列表无效")
        for peer in peers:
            _peer(peer, explicit=True)
        # Validate any legacy peer fields too; they must not conceal file input.
        for key in ("public-key", "pre-shared-key"):
            if key in node:
                _key(node[key])
    else:
        _peer(node, explicit=False)
    _reserved(node)
    _allowed_ips(node, required=False)
    _integer(node, "mtu", 576, 9000)
    _integer(node, "workers", 1, 64)
    _integer(node, "persistent-keepalive", 0, 65535)
    _integer(node, "refresh-server-ip-interval", 0, 86400)
    _booleans(node, ("udp", "remote-dns-resolve"))
    if "dns" in node:
        dns = node["dns"]
        if not isinstance(dns, list) or len(dns) > 16:
            raise ProxyError("WireGuard DNS 列表无效")
        try:
            for address in dns:
                if not isinstance(address, str):
                    raise ValueError
                ipaddress.ip_address(address)
        except ValueError as error:
            raise ProxyError("WireGuard DNS 仅支持 IP 地址") from error
