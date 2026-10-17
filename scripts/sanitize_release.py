#!/usr/bin/env python3
"""Check public source and archives without printing matched secret values."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {".env", ".npmrc", "settings.json", "candidate.json", "config.json"}
PRIVATE_PARTS = {".ssh", ".venv", "node_modules", "profiles", "logs", ".cache", "__pycache__"}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".map",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".txt",
    ".toml",
    ".sh",
    ".svg",
}
HOME_PATH = re.compile(
    r"/"
    r"Users/(?!Shared/)[^/\s\"'<>]+/|/"
    r"home/(?!deck/)[^/\s\"'<>]+/"
    r"|[A-Z]:\\Users\\[^\\\s]+\\"
)
TOKEN = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})"
)
KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
URL = re.compile(r"https?://[^\s\"'<>`\\]+")
QUERY_SECRETS = {"token", "access_token", "auth", "key", "api_key", "password", "secret"}


@dataclass(frozen=True)
class Finding:
    location: str
    rule: str
    line: int = 0


def example_host(host: str) -> bool:
    """Reserved examples are intentional regression fixtures, not credentials."""
    return host.endswith(".example") or any(
        host == domain or host.endswith("." + domain)
        for domain in ("example.com", "example.org", "example.net")
    )


def scan_text(text: str, location: str) -> list[Finding]:
    findings = []
    for pattern, rule in (
        (HOME_PATH, "private-home-path"),
        (TOKEN, "credential-token"),
        (KEY, "private-key"),
    ):
        for match in pattern.finditer(text):
            findings.append(Finding(location, rule, text.count("\n", 0, match.start()) + 1))
    for match in URL.finditer(text):
        try:
            url = urlsplit(match.group())
            host = url.hostname or ""
            if not example_host(host) and (
                url.username or url.password or QUERY_SECRETS.intersection(parse_qs(url.query))
            ):
                findings.append(
                    Finding(
                        location,
                        "subscription-credential-url",
                        text.count("\n", 0, match.start()) + 1,
                    )
                )
        except ValueError:
            # Malformed URL examples are tested by the app's boundary tests.
            continue
    return findings


def scan_name(name: str, location: str) -> list[Finding]:
    parts = PurePosixPath(name).parts
    findings = []
    if PurePosixPath(name).is_absolute() or ".." in parts:
        findings.append(Finding(location, "unsafe-archive-path"))
    if parts and (
        parts[-1] in PRIVATE_NAMES
        or parts[-1].startswith(".env.")
        and not parts[-1].endswith(".example")
        or PRIVATE_PARTS.intersection(parts)
        or parts[-1].endswith(".log")
    ):
        findings.append(Finding(location, "private-file"))
    return findings


def scan_bytes(content: bytes, name: str, location: str) -> list[Finding]:
    if name.endswith((".tar.gz", ".tgz", ".zip")):
        lock = json.loads((ROOT / "assets/core-lock.json").read_text())
        trusted = {
            f"DeckyProxy/third_party/mihomo-{lock['version']}.tar.gz": lock["source"]["sha256"],
            "DeckyProxy/third_party/pyyaml-6.0.3.tar.gz": lock["pyyaml"]["sha256"],
        }
        geo = json.loads((ROOT / "assets/geodata-lock.json").read_text())
        trusted["DeckyProxy/third_party/meta-rules-dat-source.tar.gz"] = geo["source"]["sha256"]
        if name not in trusted:
            return [Finding(location, "unexpected-embedded-archive")]
        if hashlib.sha256(content).hexdigest() != trusted[name]:
            return [Finding(location, "upstream-hash-mismatch")]
        return []
    # Scan all plaintext, including vendored frontend source. Only the exact
    # exact, hash-verified upstream archives above retain unscanned test keys.
    suffix = PurePosixPath(name).suffix
    if suffix not in TEXT_SUFFIXES and PurePosixPath(name).name not in {"LICENSE", ".gitignore"}:
        return []
    return scan_text(content.decode("utf-8", errors="replace"), location)


def scan_archive(path: Path) -> list[Finding]:
    findings = []
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            findings.extend(scan_text(archive.comment.decode(errors="replace"), path.name))
            for member in archive.infolist():
                location = f"{path.name}:{member.filename}"
                findings.extend(scan_name(member.filename, location))
                if not member.is_dir():
                    findings.extend(scan_bytes(archive.read(member), member.filename, location))
    else:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                location = f"{path.name}:{member.name}"
                findings.extend(scan_name(member.name, location))
                if member.uname not in ("", "root") or member.gname not in ("", "root"):
                    findings.append(Finding(location, "private-owner-metadata"))
                if member.issym() or member.islnk():
                    findings.append(Finding(location, "unsafe-archive-link"))
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream:
                        findings.extend(scan_bytes(stream.read(), member.name, location))
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true")
    options = parser.parse_args()
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    names = [name for name in output.decode().split("\0") if name]
    findings = []
    for name in names:
        findings.extend(scan_name(name, name))
        path = ROOT / name
        if path.is_symlink():
            findings.append(Finding(name, "unsafe-source-link"))
        elif path.is_file():
            findings.extend(scan_bytes(path.read_bytes(), name, name))
    archives = []
    if not options.source_only:
        version = json.loads((ROOT / "package.json").read_text())["version"]
        archives = [
            ROOT / "release" / f"DeckyProxy-{version}{suffix}"
            for suffix in (".zip", "-source.tar.gz")
        ]
        for path in archives:
            findings.extend(scan_archive(path))
    print(
        json.dumps(
            {
                "source_files": len(names),
                "archives": len(archives),
                "findings": [asdict(finding) for finding in findings],
            },
            indent=2,
        )
    )
    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    main()
