import io
import tarfile
import zipfile

from scripts.sanitize_release import scan_archive, scan_bytes, scan_text


def test_private_paths_and_tokens_are_detected_without_echoing_values():
    private_path = "/Users/" + "private-owner" + "/Documents/project"
    token = "ghp_" + "A" * 36
    findings = scan_text(private_path + "\n" + token, "example.txt")
    assert {f.rule for f in findings} == {"private-home-path", "credential-token"}
    assert "private-owner" not in str(findings)
    assert token not in str(findings)


def test_example_credentials_and_public_attribution_are_not_removed():
    text = (
        "https://provider.example/sub?token=test-only\n"
        "https://example.com/?token=secret\n"
        "https://github.com/MetaCubeX/mihomo\n"
        "Copyright Third Party <maintainer@example.org>\n"
        "Apple Silicon; /home/deck/homebrew/settings/DeckyProxy\n"
    )
    assert not scan_text(text, "README.md")


def test_non_example_subscription_and_private_key_are_flagged():
    text = "https://airport" + ".invalid/sub?token=not-a-real-key\n"
    text += "-----BEGIN " + "PRIVATE KEY-----"
    assert {f.rule for f in scan_text(text, "config.txt")} == {
        "subscription-credential-url",
        "private-key",
    }


def test_zip_checks_contents_names_and_metadata(tmp_path):
    target = tmp_path / "test.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("DeckyProxy/.env", "placeholder")
        archive.writestr("DeckyProxy/dist/index.js.map", "/Users/" + "private-owner" + "/code")
        archive.writestr("DeckyProxy/bin/mihomo", b"\x7fELF\x00binary")
    findings = scan_archive(target)
    assert {f.rule for f in findings} == {"private-file", "private-home-path"}


def test_source_bundle_metadata_and_unsafe_member_are_detected(tmp_path):
    target = tmp_path / "source.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        member = tarfile.TarInfo("../escape")
        member.uname = "private-owner"
        member.size = 4
        archive.addfile(member, io.BytesIO(b"test"))
    assert {f.rule for f in scan_archive(target)} == {
        "unsafe-archive-path",
        "private-owner-metadata",
    }


def test_linux_private_homes_are_detected_but_standard_deck_path_is_allowed():
    text = "/home/" + "private-owner/Documents/project"
    assert {f.rule for f in scan_text(text, "README.md")} == {"private-home-path"}
    assert not scan_text("/home/deck/homebrew/plugins/DeckyProxy", "README.md")


def test_vendored_text_is_scanned_and_opaque_archives_require_hash_verification():
    content = ("ghp_" + "B" * 36).encode()
    assert (
        scan_bytes(content, "third_party/frontend/leak.txt", "vendored")[0].rule
        == "credential-token"
    )
    assert (
        scan_bytes(b"untrusted", "third_party/unknown.tar.gz", "untrusted")[0].rule
        == "unexpected-embedded-archive"
    )
    assert (
        scan_bytes(b"tampered", "DeckyProxy/third_party/pyyaml-6.0.3.tar.gz", "upstream")[0].rule
        == "upstream-hash-mismatch"
    )
