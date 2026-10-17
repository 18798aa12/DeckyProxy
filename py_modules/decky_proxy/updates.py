"""Signed update checks and idle-only installation through an independent helper."""

import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .errors import ProxyError
from .storage import atomic_write, private_directory, write_json
from .update_helper import ACTIVE_PHASES, UpdateFailure, trusted_tree
from .update_manifest import (
    MANIFEST_URL,
    PROCESS_ENV,
    download_release,
    fsync_directory,
    verify_manifest,
    version_tuple,
)
from .update_package import extract_release


class UpdateManager:
    def __init__(self, plugin_dir: Path, runtime: Path, version: str):
        self.plugin_dir = plugin_dir
        self.runtime = runtime
        self.version = version
        self.directory = runtime / "updates"
        private_directory(self.directory)
        fsync_directory(self.directory.parent)
        self.job_path = self.directory / "job.json"
        self.health_path = self.directory / "health.json"
        self.download = download_release
        self._lock = asyncio.Lock()
        self._manifest: dict | None = None
        self._raw: bytes | None = None
        self._signature: bytes | None = None
        self._checked_at: str | None = None
        self._error: str | None = None
        self._job: dict | None = None
        self._preparing = False
        self._checking = False
        self._record_error = False

    def _supported(self) -> bool:
        return (
            platform.system() == "Linux"
            and platform.machine() in ("x86_64", "AMD64")
            and os.geteuid() == 0
            and self.plugin_dir.is_dir()
            and all(
                Path(path).is_file()
                for path in (
                    "/usr/bin/ssh-keygen",
                    "/usr/bin/systemd-run",
                    "/usr/bin/systemctl",
                    "/usr/bin/python3",
                )
            )
            and self.plugin_dir.stat().st_dev == self.directory.stat().st_dev
        )

    def _load_job(self) -> dict | None:
        if not self.job_path.exists() and not self.job_path.is_symlink():
            self._record_error = False
            return None
        try:
            if self.job_path.is_symlink() or self.job_path.stat().st_size > 8192:
                raise ValueError
            value = json.loads(self.job_path.read_bytes())
            if not isinstance(value, dict) or set(value) != {
                "plugin",
                "stage",
                "version",
                "from_version",
                "nonce",
                "unit",
                "phase",
                "error",
            }:
                raise ValueError
            nonce = value["nonce"]
            if (
                not isinstance(nonce, str)
                or len(nonce) != 32
                or any(char not in "0123456789abcdef" for char in nonce)
                or value["plugin"] != str(self.plugin_dir)
                or value["stage"] != str(self.directory / nonce / "stage")
                or value["unit"] != "deckyproxy-update-" + nonce
                or value["phase"]
                not in ACTIVE_PHASES | {"prepared", "complete", "rolled_back", "failed"}
                or not (value["error"] is None or isinstance(value["error"], str))
                or version_tuple(value["version"]) <= version_tuple(value["from_version"])
            ):
                raise ValueError
            self._record_error = False
            return value
        except (OSError, ValueError, TypeError, ProxyError) as error:
            raise ProxyError("更新记录损坏，请先手动安装新版") from error

    def _save_job(self, job: dict) -> None:
        write_json(self.job_path, job)
        fsync_directory(self.directory)
        self._job = job

    def status(self) -> dict:
        try:
            self._job = self._load_job()
        except ProxyError as error:
            self._error = str(error)
            self._record_error = True
        phase = (self._job or {}).get("phase")
        state = (
            "preparing"
            if self._preparing
            else "checking"
            if self._checking
            else "installing"
            if phase in ACTIVE_PHASES or self._record_error
            else "available"
            if phase == "prepared" or self._manifest
            else "idle"
        )
        error = self._error or (self._job or {}).get("error")
        return {
            "available": self._manifest is not None or phase == "prepared",
            "version": (self._manifest or {}).get("version")
            or ((self._job or {}).get("version") if phase == "prepared" else None),
            "checked_at": self._checked_at,
            "error": error,
            "state": state,
            "supported": self._supported(),
        }

    async def check(self) -> dict:
        async with self._lock:
            if self.status()["state"] in ("preparing", "installing"):
                return self.status()
            self._checking = True
            try:
                raw = await asyncio.to_thread(self.download, MANIFEST_URL, 8192)
                signature = await asyncio.to_thread(self.download, MANIFEST_URL + ".sig", 8192)
                manifest = await asyncio.to_thread(
                    verify_manifest,
                    raw,
                    signature,
                    self.plugin_dir / "assets/update-allowed-signers",
                    self.directory,
                )
                newer = version_tuple(manifest["version"]) > version_tuple(self.version)
                self._manifest = manifest if newer else None
                self._raw = raw if newer else None
                self._signature = signature if newer else None
                self._error = None
            except (ProxyError, OSError):
                self._manifest = None
                self._raw = None
                self._signature = None
                self._error = "无法验证新版，请检查网络后重试；当前版本未更改"
            finally:
                self._checking = False
            self._checked_at = datetime.now(UTC).isoformat()
            return self.status()

    def _prepare(self) -> None:
        if self._manifest is None or self._raw is None or self._signature is None:
            raise ProxyError("请先检查更新，当前没有可安装的新版")
        manifest = verify_manifest(
            self._raw,
            self._signature,
            self.plugin_dir / "assets/update-allowed-signers",
            self.directory,
        )
        content = self.download(manifest["url"], manifest["size"])
        if (
            len(content) != manifest["size"]
            or hashlib.sha256(content).hexdigest() != manifest["sha256"]
        ):
            raise ProxyError("更新包大小或 SHA-256 校验失败，当前版本未更改")
        previous = self._load_job()
        if previous and previous["phase"] in {"complete", "rolled_back", "failed"}:
            backup = self.directory / previous["nonce"]
            if backup.exists():
                if backup.is_symlink() or backup.resolve() != backup:
                    raise ProxyError("旧版备份路径异常，请手动检查后更新")
                shutil.rmtree(backup)
        nonce = uuid.uuid4().hex
        job_directory = self.directory / nonce
        private_directory(job_directory)
        stage = job_directory / "stage"
        try:
            extract_release(content, stage, manifest["version"])
            source = Path(__file__).with_name("update_helper.py")
            if source.is_symlink() or not source.is_file():
                raise ProxyError("更新助手缺失，请手动安装新版")
            atomic_write(job_directory / "helper.py", source.read_bytes())
            self.health_path.unlink(missing_ok=True)
            self._save_job(
                {
                    "plugin": str(self.plugin_dir),
                    "stage": str(stage),
                    "version": manifest["version"],
                    "from_version": self.version,
                    "nonce": nonce,
                    "unit": "deckyproxy-update-" + nonce,
                    "phase": "prepared",
                    "error": None,
                }
            )
        except (OSError, ProxyError):
            shutil.rmtree(job_directory)
            raise

    async def prepare_install(self) -> dict:
        async with self._lock:
            if not self._supported():
                raise ProxyError("自动安装仅支持 SteamOS 的 root 插件，请手动安装更新")
            if (self._load_job() or {}).get("phase") == "prepared":
                return self.status()
            if self.status()["state"] not in ("idle", "available"):
                raise ProxyError("已有更新任务，请等待完成")
            self._preparing = True
            try:
                task = asyncio.create_task(asyncio.to_thread(self._prepare))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    # Finish staging before releasing the lock: no concurrent prepare may
                    # race a worker that outlives cancellation of the Decky backend.
                    await task
                    raise
                self._error = None
            except ProxyError as error:
                self._error = str(error)
                raise
            except OSError as error:
                self._error = "准备更新失败，当前版本未更改"
                raise ProxyError(self._error) from error
            finally:
                self._preparing = False
            return self.status()

    def _launch(self, job: dict) -> None:
        nonce = job.get("nonce", "")
        if (
            not isinstance(nonce, str)
            or len(nonce) != 32
            or any(char not in "0123456789abcdef" for char in nonce)
            or job.get("stage") != str(self.directory / nonce / "stage")
            or job.get("plugin") != str(self.plugin_dir)
            or job.get("unit") != "deckyproxy-update-" + nonce
        ):
            raise ProxyError("更新任务路径无效，已拒绝安装")
        helper = self.directory / nonce / "helper.py"
        try:
            trusted_tree(self.plugin_dir)
            job_directory = self.directory / nonce
            metadata = job_directory.stat()
            if metadata.st_uid != 0 or metadata.st_mode & 0o077:
                raise ProxyError("更新任务目录权限不安全")
            trusted_tree(job_directory, private=job["phase"] == "prepared")
            metadata = helper.lstat()
            if helper.is_symlink() or metadata.st_uid != 0 or metadata.st_mode & 0o077:
                raise ProxyError("更新助手文件权限不安全")
            self._save_job(
                {**job, "phase": "launching" if job["phase"] == "prepared" else job["phase"]}
            )
            result = subprocess.run(
                [
                    "/usr/bin/systemd-run",
                    "--quiet",
                    "--collect",
                    "--unit=" + job["unit"],
                    "--property=Type=exec",
                    "--property=RuntimeMaxSec=200",
                    "/usr/bin/python3",
                    str(helper),
                    str(self.job_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                env=PROCESS_ENV,
            )
            if result.returncode:
                message = "无法启动独立更新任务；安装包已保留，请检查 Decky 服务后重试"
                current = self._load_job()
                if (
                    job["phase"] == "prepared"
                    and current
                    and current["nonce"] == job["nonce"]
                    and current["phase"] == "launching"
                ):
                    # A completed nonzero launch is a definite failure. Preserve
                    # the verified package while allowing the proxy to start again.
                    self._save_job({**job, "phase": "prepared", "error": message})
                self._error = message
                raise ProxyError(message)
        except (OSError, subprocess.TimeoutExpired) as error:
            # A timed-out systemd request may already have started the job. Keep
            # the installing marker until recover() checks the independent unit.
            raise ProxyError("更新任务状态待确认，请稍后重新打开插件") from error
        except UpdateFailure as error:
            self._error = str(error)
            raise ProxyError(str(error)) from error

    async def launch_install(self) -> dict:
        async with self._lock:
            if not self._supported():
                raise ProxyError("当前环境不支持自动安装")
            job = self._load_job()
            if not job or job.get("phase") != "prepared":
                raise ProxyError("没有已准备的更新包")
            await asyncio.to_thread(self._launch, {**job, "error": None})
            self._error = None
            return self.status()

    async def recover(self) -> None:
        """Resume an interrupted helper after power loss; an active unit owns recovery."""
        try:
            self._job = self._load_job()
            if (
                not self._job
                or self._job.get("phase") not in ACTIVE_PHASES
                or not self._supported()
            ):
                return
            job = self._job
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/bin/systemctl", "is-active", "--quiet", job["unit"] + ".service"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
                env=PROCESS_ENV,
            )
            if result.returncode:
                await asyncio.to_thread(self._launch, job)
        except (ProxyError, OSError, subprocess.TimeoutExpired, KeyError):
            self._error = "更新恢复需要手动检查，请保留当前配置后重新安装"

    def mark_healthy(self) -> None:
        try:
            job = self._load_job()
            if (
                job
                and job.get("phase") in ACTIVE_PHASES
                and job.get("version") == self.version
                and isinstance(job.get("nonce"), str)
            ):
                write_json(self.health_path, {"version": self.version, "nonce": job["nonce"]})
        except (ProxyError, OSError):
            self._error = "无法确认新版启动，更新助手将恢复旧版"
