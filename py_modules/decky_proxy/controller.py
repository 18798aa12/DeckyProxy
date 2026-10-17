"""Mihomo control API: loopback only, no proxy environment or raw errors."""

import asyncio
import http.client
import json

from .errors import ProxyError


class Controller:
    def __init__(self, secret: str):
        self.secret = secret

    async def request(self, method: str, path: str, body: dict | None = None) -> dict:
        return await asyncio.to_thread(self._request, method, path, body)

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        connection = http.client.HTTPConnection(
            "127.0.0.1", 19791, timeout=6 if "/delay?" in path else 2
        )
        try:
            connection.request(
                method,
                path,
                body=json.dumps(body) if body is not None else None,
                headers={
                    "Authorization": f"Bearer {self.secret}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            payload = response.read(2 * 1024 * 1024 + 1)
            if response.status not in (200, 204):
                raise ProxyError("内核拒绝操作，请刷新状态并检查节点")
            if len(payload) > 2 * 1024 * 1024:
                raise ProxyError("内核响应过大")
            value = json.loads(payload) if payload else {}
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise ProxyError("无法连接本地代理内核，请检查运行状态") from error
        finally:
            connection.close()
