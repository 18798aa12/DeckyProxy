import json
import stat

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.storage import Store


def test_defaults_atomic_settings_and_private_permissions(tmp_path):
    store = Store(tmp_path)
    state = store.load()
    assert state["auto_start"] is False
    assert state["tun_enabled"] is True
    assert state["active_profile_id"] is None
    updated = {**state, "mode": "direct"}
    store.save(updated)
    assert store.load()["mode"] == "direct"
    assert state["mode"] == "rule"
    assert stat.S_IMODE((tmp_path / "settings.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_corrupt_settings_are_reported_and_not_overwritten(tmp_path):
    store = Store(tmp_path)
    path = tmp_path / "settings.json"
    path.write_text("{broken")
    with pytest.raises(ProxyError):
        store.load()
    assert path.read_text() == "{broken"


def test_profile_roundtrip_and_no_path_traversal(tmp_path):
    store = Store(tmp_path)
    key = "a" * 32
    store.write_profile(key, {"nodes": [], "url": "https://example.com/?token=secret"})
    assert store.read_profile(key)["url"].startswith("https:")
    assert stat.S_IMODE(store.profile_path(key).stat().st_mode) == 0o600
    for bad in ["../../etc/shadow", "", "ABC", "f" * 33]:
        with pytest.raises(ProxyError):
            store.profile_path(bad)
    store.delete_profile(key)
    assert not store.profile_path(key).exists()


def test_invalid_settings_shape_rejected(tmp_path):
    store = Store(tmp_path)
    for value in [[], {"mode": "invalid"}, {"auto_start": "true"}]:
        (tmp_path / "settings.json").write_text(json.dumps(value))
        with pytest.raises(ProxyError):
            store.load()
