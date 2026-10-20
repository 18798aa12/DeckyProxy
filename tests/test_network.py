import socket

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.network import fetch_https, public_addresses, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a",
        "file:///etc/shadow",
        "https://user:pass@example.com",
        "https://127.0.0.1/a",
        "https://198.18.0.2/a",
        "https://[::1]/",
        "https://localhost/x",
        "https://example.com:22/x",
        "https://example.com/\nX: y",
    ],
)
def test_subscription_urls_reject_local_schemes_credentials_and_control_characters(url):
    with pytest.raises(ProxyError):
        validate_url(url)


def test_url_token_is_preserved_only_for_download():
    assert validate_url("https://example.com/sub?token=secret").query == "token=secret"


def test_dns_rejects_any_private_answer(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ],
    )
    with pytest.raises(ProxyError):
        public_addresses("example.com", 443)


def test_fake_ip_answers_are_still_rejected_by_the_safe_downloader(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.2", 443))])
    with pytest.raises(ProxyError, match="保留地址"):
        public_addresses("github.com", 443)


def test_dns_errors_do_not_expose_url(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("private details")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(ProxyError, match="DNS"):
        public_addresses("example.com", 443)


def test_fetch_refuses_invalid_url_before_connect():
    with pytest.raises(ProxyError):
        fetch_https("https://127.0.0.1/secret")


@pytest.mark.parametrize(
    "status,headers,payload,message",
    [
        (200, {}, b"proxies: []", None),
        (403, {}, b"private", "HTTP 403"),
        (200, {"Content-Encoding": "gzip"}, b"private", "压缩"),
        (200, {}, b"123456", "大小"),
        (302, {}, b"", "重定向"),
        (302, {"Location": "https://127.0.0.1/secret"}, b"", "公网"),
        (302, {"Location": "https://example.com/loop"}, b"", "次数"),
    ],
)
def test_download_limits_and_redirect_safety(monkeypatch, status, headers, payload, message):
    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = None
            self.remaining = payload

        def request(self, method, path, headers):
            assert headers["Accept-Encoding"] == "identity"

        def getresponse(self):
            return self

        def getheader(self, name, default=None):
            return headers.get(name, default)

        def read1(self, size):
            chunk = self.remaining[:size]
            self.remaining = self.remaining[size:]
            return chunk

        def close(self):
            pass

    Connection.status = status
    monkeypatch.setattr("decky_proxy.network.PublicHTTPSConnection", Connection)
    if message:
        with pytest.raises(ProxyError, match=message):
            fetch_https("https://example.com/sub?secret=token", max_bytes=5)
    else:
        assert fetch_https("https://example.com/sub?secret=token") == payload


def test_tls_uses_validated_ip_without_second_dns_lookup(monkeypatch):
    from decky_proxy.network import PublicHTTPSConnection

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )

    class Stream:
        def settimeout(self, value):
            pass

        def connect(self, address):
            assert address == ("8.8.8.8", 443)

        def close(self):
            pass

    class TLS:
        def wrap_socket(self, stream, server_hostname):
            assert server_hostname == "example.com"
            return stream

    monkeypatch.setattr(socket, "socket", lambda *a: Stream())
    conn = PublicHTTPSConnection("example.com")
    conn._context = TLS()
    conn.connect()
    assert isinstance(conn.sock, Stream)
