import http.client
import json

import pytest
from decky_proxy.controller import Controller
from decky_proxy.errors import ProxyError


@pytest.mark.parametrize(
    "status,payload,success",
    [
        (200, b'{"version":"1"}', True),
        (204, b"", True),
        (401, b"secret server details", False),
        (200, b"[]", False),
        (200, b"bad json", False),
        (200, b"x" * (2 * 1024 * 1024 + 1), False),
    ],
)
async def test_local_authenticated_api_and_safe_errors(monkeypatch, status, payload, success):
    class Connection:
        closed = False

        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1" and port == 19791

        def request(self, method, path, body, headers):
            assert headers["Authorization"] == "Bearer test-secret"
            assert json.loads(body) == {"mode": "rule"}

        def getresponse(self):
            return self

        def read(self, limit):
            return payload[:limit]

        def close(self):
            self.closed = True

    Connection.status = status
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    controller = Controller("test-secret")
    if success:
        result = await controller.request("PATCH", "/configs", {"mode": "rule"})
        assert isinstance(result, dict)
    else:
        with pytest.raises(ProxyError) as caught:
            await controller.request("PATCH", "/configs", {"mode": "rule"})
        assert "secret" not in str(caught.value)


async def test_connection_failure_sanitized(monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise OSError("private error")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", Broken)
    with pytest.raises(ProxyError, match="本地"):
        await Controller("secret").request("GET", "/version")
