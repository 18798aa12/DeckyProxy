import hashlib
import io
import json
import stat
import zipfile

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.update_package import extract_release


def package(version="0.2.1", extra=None):
    core = b"\x7fELF\x02\x01" + b"\x00" * 12 + b"\x3e\x00" + b"core"
    files = {
        "DeckyProxy/main.py": b"# plugin\n",
        "DeckyProxy/plugin.json": json.dumps({"name": "DeckyProxy", "flags": ["root"]}).encode(),
        "DeckyProxy/package.json": json.dumps({"version": version}).encode(),
        "DeckyProxy/dist/index.js": b"export default {};",
        "DeckyProxy/bin/mihomo": core,
        "DeckyProxy/assets/core-lock.json": json.dumps(
            {"assets": {"linux-amd64": {"unpacked_sha256": hashlib.sha256(core).hexdigest()}}}
        ).encode(),
        "DeckyProxy/assets/update-allowed-signers": b"public key",
        "DeckyProxy/py_modules/decky_proxy/updates.py": b"# updater\n",
        "DeckyProxy/py_modules/decky_proxy/update_helper.py": b"# helper\n",
        "DeckyProxy/py_modules/decky_proxy/safe_regex.py": b"# filter normalization\n",
        "DeckyProxy/py_modules/decky_proxy/regex_worker.py": b"# isolated worker\n",
        "DeckyProxy/py_modules/decky_proxy/version.py": b"# installed package version\n",
    }
    files.update(extra or {})
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, content)
    return result.getvalue()


@pytest.mark.parametrize("module", ["safe_regex.py", "regex_worker.py", "version.py"])
def test_update_requires_complete_filter_runtime(tmp_path, module):
    source = io.BytesIO(package())
    result = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(result, "w") as new:
        for member in old.infolist():
            if member.filename != f"DeckyProxy/py_modules/decky_proxy/{module}":
                new.writestr(member, old.read(member))
    with pytest.raises(ProxyError, match="必需文件"):
        extract_release(result.getvalue(), tmp_path / "stage", "0.2.1")
    assert not (tmp_path / "stage").exists()


def test_extracts_only_valid_new_plugin(tmp_path):
    stage = tmp_path / "stage"
    extract_release(package(), stage, "0.2.1")
    assert (stage / "package.json").is_file()
    assert (stage / "bin/mihomo").stat().st_mode & 0o777 == 0o700
    assert stage.stat().st_mode & 0o777 == 0o700
    assert (stage / "main.py").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "name",
    [
        "DeckyProxy/../../outside",
        "/tmp/absolute",
        "Other/main.py",
        "DeckyProxy/./main.py",
        "DeckyProxy/settings/subscription.json",
        "DeckyProxy/a\\b",
        "DeckyProxy/.env",
    ],
)
def test_rejects_unsafe_member_paths_and_cleans_partial_stage(tmp_path, name):
    stage = tmp_path / "stage"
    with pytest.raises(ProxyError):
        extract_release(package(extra={name: b"bad"}), stage, "0.2.1")
    assert not stage.exists()


def test_rejects_wrong_version_core_hash_symlinks_and_duplicate_members(tmp_path):
    cases = [package("0.2.0"), package(extra={"DeckyProxy/bin/mihomo": b"bad core"}), b"invalid"]
    for payload in cases:
        with pytest.raises(ProxyError):
            extract_release(payload, tmp_path / "stage", "0.2.1")
    stream = io.BytesIO(package())
    with zipfile.ZipFile(stream, "a") as archive:
        info = zipfile.ZipInfo("DeckyProxy/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(ProxyError):
        extract_release(stream.getvalue(), tmp_path / "stage", "0.2.1")
    stream = io.BytesIO(package())
    with zipfile.ZipFile(stream, "a") as archive:
        archive.writestr("DeckyProxy/main.py", "duplicate")
    with pytest.raises(ProxyError):
        extract_release(stream.getvalue(), tmp_path / "stage", "0.2.1")
