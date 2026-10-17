#!/usr/bin/env python3
"""Build a Decky ZIP and an accompanying, self-contained source bundle."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from build_common import ROOT, atomic_bytes, download_verified, load_lock, sha256_file
from fetch_core import fetch_core

PLUGIN_NAME = "DeckyProxy"
RELEASE = ROOT / "release"
ZIP_EPOCH = (2024, 1, 1, 0, 0, 0)
EXCLUDED_NAMES = frozenset({"__pycache__", ".DS_Store", ".pytest_cache"})


def checked_files(directory: Path) -> list[Path]:
    """Enumerate only release source files; reject symlink surprises."""
    files = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Release input cannot be a symlink: {path}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo", ".so", ".dylib"}:
            files.append(path)
    return files


def vendor_yaml(destination: Path) -> Path:
    """Extract only the pure-Python PyYAML modules and their MIT license."""
    lock = load_lock()
    source = download_verified(lock["pyyaml"], "pyyaml-6.0.3.tar.gz", maximum_bytes=2 * 1024 * 1024)
    module_root = destination / "py_modules" / "yaml"
    count = 0
    with tarfile.open(source, "r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if not member.isfile() or len(path.parts) < 2:
                continue
            if len(path.parts) == 4 and path.parts[1:3] == ("lib", "yaml"):
                if path.suffix != ".py":
                    continue
                target = module_root / path.name
                count += 1
            elif len(path.parts) == 2 and path.name == "LICENSE":
                target = module_root / "LICENSE"
            else:
                continue
            stream = archive.extractfile(member)
            if stream is None or member.size > 1024 * 1024:
                raise ValueError("Unexpected PyYAML source member")
            atomic_bytes(target, stream.read())
    if count < 10 or not (module_root / "LICENSE").is_file():
        raise ValueError("PyYAML source layout changed; review the vendor step")
    return source


def stage_plugin(destination: Path) -> tuple[Path, Path]:
    """Copy an explicit allowlist, never settings, logs, caches or credentials."""
    binary, core_source = fetch_core()
    required = (
        "dist/index.js",
        "main.py",
        "plugin.json",
        "package.json",
        "assets/core-lock.json",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "README.md",
    )
    for relative in required:
        source = ROOT / relative
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing/unsafe release input: {relative}")
        atomic_bytes(destination / relative, source.read_bytes())
    module_dir = ROOT / "py_modules"
    if not module_dir.is_dir() or not list(module_dir.rglob("*.py")):
        raise ValueError("No Python backend modules found")
    for path in checked_files(module_dir):
        if path.suffix == ".py":
            atomic_bytes(
                destination / "py_modules" / path.relative_to(module_dir), path.read_bytes()
            )
    documentation = ROOT / "docs"
    for path in checked_files(documentation):
        if path.suffix == ".md":
            atomic_bytes(destination / "docs" / path.relative_to(documentation), path.read_bytes())
    atomic_bytes(destination / "bin" / "mihomo", binary.read_bytes(), 0o755)
    yaml_source = vendor_yaml(destination)
    atomic_bytes(destination / "licenses" / "MIHOMO-LICENSE", (ROOT / "LICENSE").read_bytes())
    for name, module in frontend_modules().items():
        license_name = "LICENSE.txt" if name == "tslib" else "LICENSE"
        atomic_bytes(
            destination / "licenses" / f"{name}-LICENSE", (module / license_name).read_bytes()
        )
    source_map = ROOT / "dist" / "index.js.map"
    if source_map.is_file() and not source_map.is_symlink():
        atomic_bytes(destination / "dist" / "index.js.map", source_map.read_bytes())
    return core_source, yaml_source


def frontend_modules() -> dict[str, Path]:
    """Locate the exact installed libraries whose code can enter the JS bundle."""
    modules = {"decky-api": "@decky/api", "react-icons": "react-icons", "tslib": "tslib"}
    with (ROOT / "package.json").open(encoding="utf-8") as stream:
        dependencies = json.load(stream)["dependencies"]
    result = {}
    for name, package in modules.items():
        directory = (ROOT / "node_modules" / package).resolve(strict=True)
        with (directory / "package.json").open(encoding="utf-8") as stream:
            installed = json.load(stream)
        if installed["version"] != dependencies[package]:
            raise ValueError(f"Installed {package} does not match package.json")
        result[name] = directory
    return result


def frontend_sources() -> list[tuple[Path, str]]:
    """Bundle library source and notices, including LGPL Decky API sources."""
    result = []
    for name, directory in frontend_modules().items():
        for path in checked_files(directory):
            relative = path.relative_to(directory)
            if name == "react-icons" and len(relative.parts) > 1:
                if relative.parts[0] not in {"fa", "lib"}:
                    continue
            result.append(
                (path, f"{PLUGIN_NAME}/third_party/frontend/{name}/{relative.as_posix()}")
            )
    return result


def build_zip(staged: Path, target: Path) -> None:
    """Write stable ZIP metadata with the executable bit on the Linux core."""
    temporary = target.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in checked_files(staged):
                relative = path.relative_to(staged)
                info = zipfile.ZipInfo(f"{PLUGIN_NAME}/{relative.as_posix()}", ZIP_EPOCH)
                info.create_system = 3
                mode = 0o755 if relative.as_posix() == "bin/mihomo" else 0o644
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def source_files() -> list[Path]:
    """Keep application and build sources without user data or dependencies."""
    directories = ("src", "py_modules", "scripts", "assets", "docs", "tests", ".github")
    files = []
    for name in directories:
        directory = ROOT / name
        if directory.is_dir():
            files.extend(checked_files(directory))
    root_files = (
        "main.py",
        "plugin.json",
        "package.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements.txt",
        "rollup.config.mjs",
        "tsconfig.json",
        "vitest.config.ts",
        ".gitignore",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "README.md",
    )
    return sorted({*files, *(ROOT / name for name in root_files if (ROOT / name).is_file())})


def add_tar_file(archive: tarfile.TarFile, path: Path, name: str) -> None:
    """Add ordinary file bytes with deterministic, non-user-specific metadata."""
    content = path.read_bytes()
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def build_source_bundle(target: Path, core_source: Path, yaml_source: Path) -> None:
    """Include exact upstream archives alongside all plugin/build source code."""
    temporary = target.with_suffix(".gz.tmp")
    try:
        with temporary.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for path in source_files():
                        add_tar_file(
                            archive, path, f"{PLUGIN_NAME}/{path.relative_to(ROOT).as_posix()}"
                        )
                    for path in (core_source, yaml_source):
                        add_tar_file(archive, path, f"{PLUGIN_NAME}/third_party/{path.name}")
                    for path, name in frontend_sources():
                        add_tar_file(archive, path, name)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Produce the installable ZIP, full source companion and their SHA256s."""
    with (ROOT / "package.json").open(encoding="utf-8") as stream:
        version = json.load(stream)["version"]
    if (
        not isinstance(version, str)
        or not version
        or any(
            char not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-"
            for char in version
        )
    ):
        raise ValueError("Package version must be safe for a release filename")
    RELEASE.mkdir(exist_ok=True)
    zip_path = RELEASE / f"{PLUGIN_NAME}-{version}.zip"
    source_path = RELEASE / f"{PLUGIN_NAME}-{version}-source.tar.gz"
    with tempfile.TemporaryDirectory(prefix="decky-proxy-package-") as directory:
        staged = Path(directory) / PLUGIN_NAME
        core_source, yaml_source = stage_plugin(staged)
        build_zip(staged, zip_path)
        build_source_bundle(source_path, core_source, yaml_source)
    checksums = "".join(f"{sha256_file(path)}  {path.name}\n" for path in (zip_path, source_path))
    atomic_bytes(RELEASE / "SHA256SUMS", checksums.encode("utf-8"))
    print(checksums, end="")


if __name__ == "__main__":
    main()
