"""Public HTTPS downloads, with pinned DNS addresses and checked redirects."""

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import SplitResult, urljoin, urlsplit

from .errors import ProxyError


def validate_url(url: str) -> SplitResult:
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise ProxyError("请输入 HTTPS 订阅地址")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)
            or "\\" in url
        ):
            raise ValueError
        if host.lower().rstrip(".") == "localhost" or host.lower().endswith(
            (".local", ".localhost")
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host.encode("idna")
        else:
            if not address.is_global:
                raise ValueError
    except (ValueError, UnicodeError) as error:
        raise ProxyError("订阅仅支持无用户名密码的 HTTPS 公网地址（443 端口）") from error
    return parsed


def public_addresses(host: str, port: int) -> list[tuple]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ProxyError("订阅服务器 DNS 解析失败，请检查网络") from error
    if not answers or any(not ipaddress.ip_address(answer[4][0]).is_global for answer in answers):
        raise ProxyError("订阅服务器解析到内网或保留地址，已拒绝连接")
    return answers


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        addresses = public_addresses(self.host, self.port)
        failure: OSError | None = None
        for family, kind, protocol, _, address in addresses:
            stream = socket.socket(family, kind, protocol)
            stream.settimeout(self.timeout)
            try:
                stream.connect(address)
                self.sock = self._context.wrap_socket(stream, server_hostname=self.host)
                return
            except OSError as error:
                stream.close()
                failure = error
        raise ProxyError("无法建立安全 HTTPS 连接，请检查网络和服务器证书") from failure


def fetch_https(url: str, max_bytes: int = 4 * 1024 * 1024) -> bytes:
    current = url
    deadline = time.monotonic() + 30
    for _ in range(5):
        parsed = validate_url(current)
        connection = PublicHTTPSConnection(
            parsed.hostname.encode("idna").decode(),
            timeout=25,
            context=ssl.create_default_context(),
        )
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(
                "GET",
                path,
                headers={"User-Agent": "clash.meta/DeckyProxy", "Accept-Encoding": "identity"},
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ProxyError("订阅重定向缺少目标地址")
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ProxyError(f"下载失败：服务器返回 HTTP {response.status}")
            if response.getheader("Content-Encoding", "identity") not in ("identity", ""):
                raise ProxyError("服务器忽略了禁用压缩请求，请使用直接 YAML 链接")
            chunks = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProxyError("HTTPS 下载超过 30 秒，请检查网络后重试")
                if connection.sock:
                    connection.sock.settimeout(min(25, remaining))
                chunk = response.read1(min(65536, max_bytes + 1 - total))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise ProxyError("下载文件超过大小限制")
        except (OSError, http.client.HTTPException, UnicodeError) as error:
            raise ProxyError("HTTPS 下载失败，请检查网络、证书和订阅地址") from error
        finally:
            connection.close()
    raise ProxyError("订阅重定向次数过多")
