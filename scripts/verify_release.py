#!/usr/bin/env python3
"""Audit the actual published ZIP/source pair without executing packaged code."""

from __future__ import annotations

import hashlib
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from build_common import ROOT, sha256_file


def require(condition: bool, message: str) -> None:
    """Fail the release audit on the first concrete packaging problem."""
    if not condition:
        raise ValueError(message)


def verify_zip(path: Path) -> dict:
    """Check architecture, hashes, permissions, dependencies and data exclusion."""
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "ZIP has a corrupt member")
        names = archive.namelist()
        require(len(names) == len(set(names)), "ZIP contains duplicate member names")
        required = {
            "dist/index.js",
            "main.py",
            "plugin.json",
            "package.json",
            "bin/mihomo",
            "assets/core-lock.json",
            "assets/geodata-lock.json",
            "assets/update-allowed-signers",
            "bin/geodata/geoip.dat",
            "bin/geodata/geosite.dat",
            "bin/geodata/ASN.mmdb",
            "licenses/GEO-DATA-LICENSE",
            "licenses/DBIP-DATA-LICENSE",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "README.md",
            "docs/STEAM_DECK_TESTING.md",
            "docs/RESEARCH.md",
            "py_modules/yaml/__init__.py",
            "py_modules/yaml/constructor.py",
            "py_modules/yaml/LICENSE",
            "licenses/MIHOMO-LICENSE",
            "licenses/decky-api-LICENSE",
            "licenses/react-icons-LICENSE",
            "licenses/tslib-LICENSE",
        }
        require(
            {f"DeckyProxy/{item}" for item in required} <= set(names),
            "ZIP is missing release inputs",
        )
        forbidden = {".env", ".venv", "node_modules", "settings", "logs", ".cache", "__pycache__"}
        for name in names:
            member = PurePosixPath(name)
            require(member.parts[0] == "DeckyProxy", "ZIP has an unexpected root directory")
            require(not member.is_absolute() and ".." not in member.parts, "Unsafe ZIP member path")
            require(
                not forbidden.intersection(member.parts), "ZIP includes development or user data"
            )
            require(
                member.suffix not in {".pyc", ".so", ".dylib"},
                "ZIP includes a platform Python extension",
            )
        lock = json.loads(archive.read("DeckyProxy/assets/core-lock.json"))
        core = archive.read("DeckyProxy/bin/mihomo")
        geo = json.loads(archive.read("DeckyProxy/assets/geodata-lock.json"))
        for name, spec in geo["files"].items():
            require(name in {"geoip.dat", "geosite.dat", "ASN.mmdb"}, "Unexpected GEO data file")
            require(
                hashlib.sha256(archive.read(f"DeckyProxy/bin/geodata/{name}")).hexdigest()
                == spec["sha256"],
                "Bundled GEO data SHA256 mismatch",
            )
        require(
            archive.read("DeckyProxy/assets/update-allowed-signers").startswith(
                b"deckyproxy-release "
            ),
            "Release verification key missing",
        )
        require(
            core[:6] == b"\x7fELF\x02\x01" and core[18:20] == b"\x3e\x00", "Core is not Linux amd64"
        )
        require(
            hashlib.sha256(core).hexdigest() == lock["assets"]["linux-amd64"]["unpacked_sha256"],
            "Packaged core SHA256 differs from lock",
        )
        mode = archive.getinfo("DeckyProxy/bin/mihomo").external_attr >> 16
        require(mode & 0o777 == 0o755, "Packaged core is not executable")
        require(
            json.loads(archive.read("DeckyProxy/plugin.json"))["flags"] == ["root"],
            "Plugin needs root flag",
        )
        for name in names:
            if name.endswith(".py"):
                compile(archive.read(name), name, "exec", dont_inherit=True)
    return lock


def verify_source(path: Path, lock: dict) -> None:
    """Require exact upstream archives and editable bundled LGPL library source."""
    with tarfile.open(path, "r:gz") as archive:
        geo = json.loads((ROOT / "assets/geodata-lock.json").read_text())
        members = {member.name: member for member in archive.getmembers()}
        require("DeckyProxy/scripts/package.py" in members, "Source bundle lacks build script")
        require("DeckyProxy/pnpm-lock.yaml" in members, "Source bundle lacks frontend lock")
        geo_member = archive.extractfile("DeckyProxy/third_party/meta-rules-dat-source.tar.gz")
        require(geo_member is not None, "Source bundle lacks GEO data build scripts")
        if geo_member:
            require(
                hashlib.sha256(geo_member.read()).hexdigest() == geo["source"]["sha256"],
                "GEO build scripts source SHA256 mismatch",
            )
        require(
            any(
                name.startswith("DeckyProxy/third_party/frontend/decky-api/src/")
                for name in members
            ),
            "Source bundle lacks editable LGPL Decky API sources",
        )
        for component, filename in (
            ("source", f"mihomo-{lock['version']}.tar.gz"),
            ("pyyaml", "pyyaml-6.0.3.tar.gz"),
        ):
            name = f"DeckyProxy/third_party/{filename}"
            require(name in members, f"Source bundle lacks {filename}")
            stream = archive.extractfile(members[name])
            require(stream is not None, "Source archive member is not an ordinary file")
            if stream is not None:
                require(
                    hashlib.sha256(stream.read()).hexdigest() == lock[component]["sha256"],
                    f"Bundled {filename} SHA256 mismatch",
                )


def main() -> None:
    """Verify the current version's release files against their checksum list."""
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    directory = ROOT / "release"
    zip_path = directory / f"DeckyProxy-{version}.zip"
    source_path = directory / f"DeckyProxy-{version}-source.tar.gz"
    checksums = {
        name: digest
        for digest, name in (
            line.split() for line in (directory / "SHA256SUMS").read_text().splitlines()
        )
    }
    for path in (zip_path, source_path):
        require(
            sha256_file(path) == checksums.get(path.name), f"Release checksum mismatch: {path.name}"
        )
    lock = verify_zip(zip_path)
    verify_source(source_path, lock)
    print("Release audit passed: core, pure-Python YAML, permissions, licenses and source bundle")


if __name__ == "__main__":
    main()
