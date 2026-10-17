"""Verified core binary and bounded lifecycle of this plugin's own child."""

import asyncio
import gzip
import hashlib
import io
import json
import os
import platform
import shutil
import socket
from pathlib import Path

from .errors import ProxyError
from .geodata import prepare_geodata
from .network import fetch_https
from .storage import atomic_write, private_directory


def _numeric_identifier(value: object) -> object:
    """iproute2 serializes route tables as strings, even with numeric output."""
    if (
        isinstance(value, str)
        and 0 < len(value) <= 10
        and value.isascii()
        and value.isdecimal()
        and int(value) <= 0xFFFFFFFF
    ):
        return int(value)
    return value


class Core:
    def __init__(self, runtime: Path, plugin_dir: Path):
        self.runtime = runtime
        self.plugin_dir = plugin_dir
        self._process: asyncio.subprocess.Process | None = None
        self._verified: tuple | None = None
        private_directory(runtime)
        try:
            self.lock = json.loads((plugin_dir / "assets" / "core-lock.json").read_text())
            self.asset = self.lock["assets"]["linux-amd64"]
            self.version = self.lock["version"]
        except (OSError, ValueError, KeyError) as error:
            raise ProxyError("内核版本锁文件缺失，请重新安装完整插件 ZIP") from error

    @property
    def supported(self) -> bool:
        return platform.system() == "Linux" and platform.machine() in ("x86_64", "amd64")

    @property
    def binary(self) -> Path:
        local = self.runtime / "bin" / "mihomo"
        return local if local.exists() else self.plugin_dir / "bin" / "mihomo"

    @property
    def installed(self) -> bool:
        path = self.binary
        try:
            if path.is_symlink() or not path.is_file():
                return False
            info = path.stat()
            signature = (str(path), info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
            if signature != self._verified:
                if hashlib.sha256(path.read_bytes()).hexdigest() != self.asset.get(
                    "unpacked_sha256"
                ):
                    return False
                self._verified = signature
            return True
        except OSError:
            return False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _environment(self) -> dict[str, str]:
        return {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": str(self.runtime),
            "LANG": "C.UTF-8",
        }

    async def install(self) -> None:
        if not self.supported:
            raise ProxyError("内核安装仅支持 SteamOS/Linux x86_64")
        if self.running:
            raise ProxyError("请先停止代理，再安装内核")
        payload = await asyncio.to_thread(fetch_https, self.asset["url"], 40 * 1024 * 1024)
        if hashlib.sha256(payload).hexdigest() != self.asset["sha256"]:
            raise ProxyError("内核下载 SHA256 校验失败，已拒绝安装")
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as archive:
                binary = archive.read(120 * 1024 * 1024 + 1)
        except (OSError, EOFError) as error:
            raise ProxyError("内核压缩包损坏") from error
        if len(binary) > 120 * 1024 * 1024 or not binary.startswith(b"\x7fELF"):
            raise ProxyError("内核文件格式或大小不正确")
        if hashlib.sha256(binary).hexdigest() != self.asset.get("unpacked_sha256"):
            raise ProxyError("解压后内核 SHA256 校验失败")
        await asyncio.to_thread(atomic_write, self.runtime / "bin" / "mihomo", binary, 0o700)

    def _check(self) -> None:
        if not self.supported:
            raise ProxyError("代理进程仅能在 SteamOS/Linux x86_64 启动")
        if not self.installed:
            raise ProxyError("内核缺失或校验失败，请安装完整 ZIP 或点击安装内核")
        # Decky's ZipFile.extractall does not preserve executable permission bits.
        self.binary.chmod(0o700)

    async def validate(self, path: Path) -> None:
        await asyncio.to_thread(self._check)
        config = json.loads(await asyncio.to_thread(path.read_text))
        await asyncio.to_thread(prepare_geodata, self.plugin_dir, self.runtime, config)
        process = await self._spawn(
            str(self.binary),
            "-t",
            "-f",
            str(path),
            "-d",
            str(self.runtime),
            env=self._environment(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise ProxyError("内核配置校验失败，请检查订阅节点的协议参数")

    async def _preflight(self, path: Path) -> None:
        config = json.loads(await asyncio.to_thread(path.read_text))
        if config["tun"]["enable"]:
            if os.geteuid() != 0 or not await asyncio.to_thread(Path("/dev/net/tun").exists):
                raise ProxyError("TUN 需要 Decky root 权限和 /dev/net/tun 设备")
            if await asyncio.to_thread(Path("/sys/class/net/DeckyProxy").exists):
                raise ProxyError("DeckyProxy TUN 接口已占用，请先停止其他代理或重启设备")
            rules = await self._ip_json("rule", "show")
            if any(
                rule.get("table") == 19792 or 19793 <= rule.get("priority", 0) <= 19803
                for rule in rules
            ):
                raise ProxyError("插件使用的路由表/规则已占用，请先停用其他 TUN 代理")
            routes = await self._ip_json("route", "show", "table", "all")
            if any(route.get("table") == 19792 for route in routes):
                raise ProxyError("插件路由表已有路由，请先停用冲突的 TUN 代理")
        for port, kind in [
            (19790, socket.SOCK_STREAM),
            (19791, socket.SOCK_STREAM),
            (19792, socket.SOCK_DGRAM),
            (19792, socket.SOCK_STREAM),
        ]:
            try:
                with socket.socket(socket.AF_INET, kind) as probe:
                    if kind == socket.SOCK_STREAM:
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise ProxyError(f"本地端口 {port} 已占用，请先关闭冲突应用") from error

    async def _ip_json(self, *args: str) -> list[dict]:
        ip = shutil.which("ip", path="/usr/sbin:/usr/bin:/sbin:/bin")
        if not ip:
            raise ProxyError("系统缺少 iproute2，无法检查 TUN 路由")
        process = await self._spawn(
            ip,
            "-j",
            "-N",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=self._environment(),
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 5)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise ProxyError("无法检查路由，请先检查系统网络")
        try:
            data = json.loads(output)
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError
            records = [
                {
                    key: _numeric_identifier(value) if key in ("table", "priority") else value
                    for key, value in row.items()
                }
                for row in data
            ]
            if any(
                "priority" in row
                and (type(row["priority"]) is not int or not 0 <= row["priority"] <= 0xFFFFFFFF)
                for row in records
            ):
                raise ValueError
            return records
        except ValueError as error:
            raise ProxyError("系统路由检查返回无效数据") from error

    async def assert_ready(self, tun: bool) -> None:
        if tun:
            if not await asyncio.to_thread(Path("/sys/class/net/DeckyProxy").exists):
                raise ProxyError("TUN 接口未建立，已停止代理，请检查权限和其他代理")
            routes = await self._ip_json("route", "show", "table", "all")
            if not any(r.get("table") == 19792 and r.get("dev") == "DeckyProxy" for r in routes):
                raise ProxyError("TUN 路由未建立，已停止代理，请检查网络冲突")

    async def start(self, path: Path) -> None:
        await asyncio.to_thread(self._check)
        if self.running:
            return
        await self._preflight(path)
        python = shutil.which("python3", path="/usr/bin:/bin")
        if not python:
            raise ProxyError("系统缺少 Python 3，无法启动内核退出保护程序")
        runner = Path(__file__).with_name("runner.py")
        self.binary.chmod(0o700)
        self._process = await self._spawn(
            python,
            str(runner),
            str(os.getpid()),
            str(self.binary),
            "-f",
            str(path),
            "-d",
            str(self.runtime),
            env=self._environment(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _spawn(self, *args: str, **kwargs) -> asyncio.subprocess.Process:
        # Cancellation can arrive after fork but before asyncio hands back the
        # process handle. Retain that handle and reap the child in this window.
        pending = asyncio.create_task(asyncio.create_subprocess_exec(*args, **kwargs))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            process = await pending
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 8)
                except TimeoutError:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
            raise

    async def stop(self) -> None:
        process = self._process
        if not process:
            return
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 8)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.wait()
        self._process = None
