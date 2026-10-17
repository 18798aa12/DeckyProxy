import os

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.profile_files import LocalYamlFiles

from tests.test_configuration import YAML


@pytest.fixture
def files(tmp_path):
    home = tmp_path / "deck"
    (home / "Downloads").mkdir(parents=True)
    return LocalYamlFiles(home, os.getuid())


def test_reads_bom_yaml_from_downloads_and_documents_without_persisting_path(files):
    target = files.home / "Downloads" / "我的配置.YAML"
    target.write_bytes(b"\xef\xbb\xbf" + YAML.encode())
    assert files.read(str(target)) == YAML
    assert files.start_directory() == str(target.parent)
    (files.home / "Documents").mkdir()
    target = files.home / "Documents" / "profile.yml"
    target.write_text(YAML)
    assert files.read(str(target)) == YAML


def test_xdg_localized_download_directory_is_supported(files):
    (files.home / ".config").mkdir()
    (files.home / "下载").mkdir()
    (files.home / ".config" / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/下载"\n')
    target = files.home / "下载" / "clash.yaml"
    target.write_text(YAML)
    assert files.start_directory() == str(target.parent)
    assert files.read(str(target)) == YAML


@pytest.mark.parametrize("bad", ["relative.yaml", "/etc/shadow", "", 123, "/a\x00.yaml"])
def test_invalid_paths_are_rejected(files, bad):
    with pytest.raises(ProxyError):
        files.read(bad)


def test_only_approved_nonhidden_yaml_files_are_read(files, tmp_path):
    paths = [
        tmp_path / "outside.yaml",
        files.home / "private.yaml",
        files.home / "Downloads" / "wrong.txt",
        files.home / "Downloads" / ".hidden.yaml",
        files.home / "Downloads" / "folder.yaml",
    ]
    for target in paths:
        if target.name == "folder.yaml":
            target.mkdir()
        else:
            target.write_text(YAML)
        with pytest.raises(ProxyError):
            files.read(str(target))


def test_symlink_files_ancestors_and_fifo_are_rejected_without_following_or_blocking(
    files, tmp_path
):
    outside = tmp_path / "outside.yaml"
    outside.write_text(YAML)
    link = files.home / "Downloads" / "link.yaml"
    link.symlink_to(outside)
    with pytest.raises(ProxyError):
        files.read(str(link))
    alias = files.home / "Downloads" / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ProxyError):
        files.read(str(alias / "outside.yaml"))
    fifo = files.home / "Downloads" / "pipe.yaml"
    os.mkfifo(fifo)
    with pytest.raises(ProxyError):
        files.read(str(fifo))


def test_oversize_invalid_encoding_and_foreign_owner_are_rejected(files, monkeypatch):
    target = files.home / "Downloads" / "large.yaml"
    target.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ProxyError, match="4 MiB"):
        files.read(str(target))
    target.write_bytes(b"\xff")
    with pytest.raises(ProxyError, match="UTF-8"):
        files.read(str(target))
    target.write_text(YAML)
    files.uid = os.getuid() + 10000
    with pytest.raises(ProxyError, match="所有者"):
        files.read(str(target))


def test_xdg_cannot_enable_hidden_or_outside_or_shell_expansion_paths(files, tmp_path):
    (files.home / ".config").mkdir()
    (files.home / ".secret").mkdir()
    settings = files.home / ".config" / "user-dirs.dirs"
    for value in [str(tmp_path), "$HOME/.secret", "$(touch bad)/Downloads", "$HOME/"]:
        settings.write_text('XDG_DOWNLOAD_DIR="' + value + '"\n')
        assert files.start_directory() == str(files.home / "Downloads")


async def test_file_import_uses_same_profile_pipeline_and_safe_metadata(service, tmp_path):
    service.files = LocalYamlFiles(tmp_path, os.getuid())
    (tmp_path / "Downloads").mkdir()
    target = tmp_path / "Downloads" / "游戏配置.yaml"
    target.write_text(YAML)
    result = await service.import_profile_file("", str(target))
    assert result["profiles"][0]["name"] == "游戏配置"
    assert result["profiles"][0]["source_host"] is None
    assert str(target) not in str(result)
    assert await service.get_import_directory() == str(target.parent)
    target.unlink()
    assert (await service.start_proxy())["running"]
