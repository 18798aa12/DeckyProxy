#!/usr/bin/env python3
"""Sign a built release with an external Ed25519 key; never bundle the private key."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from build_common import ROOT, atomic_bytes

sys.path.insert(0, str(ROOT / "py_modules"))
from decky_proxy.update_manifest import parse_manifest, verify_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--key",
        type=Path,
        default=Path.home() / ".local/share/DeckyProxy/release-signing/release_ed25519",
    )
    options = parser.parse_args()
    key = options.key.expanduser().resolve()
    if key.is_relative_to(ROOT) or not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError("Signing key must be a private file outside the repository")
    version = json.loads((ROOT / "package.json").read_text())["version"]
    release = ROOT / "release"
    package = release / f"DeckyProxy-{version}.zip"
    raw = (
        json.dumps(
            {
                "schema": 1,
                "version": version,
                "platform": "linux-amd64",
                "url": f"https://github.com/18798aa12/DeckyProxy/releases/download/v{version}/{package.name}",
                "size": package.stat().st_size,
                "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    parse_manifest(raw)
    output = release / "update.json"
    atomic_bytes(output, raw)
    signature = release / "update.json.sig"
    signature.unlink(missing_ok=True)
    subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(key),
            "-n",
            "deckyproxy-update",
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    verify_manifest(raw, signature.read_bytes(), ROOT / "assets/update-allowed-signers", release)
    with (release / "SHA256SUMS").open("a") as stream:
        for path in (output, signature):
            stream.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    os.chmod(signature, 0o644)
    print(f"Signed and verified DeckyProxy {version} update manifest")


if __name__ == "__main__":
    main()
