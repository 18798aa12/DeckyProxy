"""The privileged smoke must prove isolation before changing network or mounts."""

import importlib.util
import json
from pathlib import Path

import pytest


def load_smoke():
    path = Path(__file__).resolve().parent.parent / "scripts" / "linux_tun_smoke.py"
    spec = importlib.util.spec_from_file_location("linux_tun_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("same_namespace", ["net", "mnt", "both"])
def test_guard_rejects_shared_namespace(monkeypatch, same_namespace):
    smoke = load_smoke()

    def identity(pid, namespace):
        return 1 if namespace == same_namespace or same_namespace == "both" else pid

    monkeypatch.setattr(smoke, "namespace_identity", identity)
    monkeypatch.setattr(smoke.os, "getpid", lambda: 200)
    with pytest.raises(RuntimeError, match="isolated"):
        smoke.assert_isolated(100)


def test_guard_accepts_both_private_namespaces(monkeypatch):
    smoke = load_smoke()
    monkeypatch.setattr(smoke, "namespace_identity", lambda pid, namespace: pid)
    monkeypatch.setattr(smoke.os, "getpid", lambda: 200)
    smoke.assert_isolated(100)


def test_child_never_mutates_mounts_or_links_before_isolation(monkeypatch):
    smoke = load_smoke()
    mutations = []

    def reject(parent_pid):
        raise RuntimeError("not isolated")

    monkeypatch.setattr(smoke, "assert_isolated", reject)
    monkeypatch.setattr(smoke, "command", lambda *arguments: mutations.append(arguments))
    with pytest.raises(RuntimeError, match="not isolated"):
        smoke.run_inside(100)
    assert mutations == []


def test_synthetic_profile_has_no_downloads_or_health_checks():
    smoke = load_smoke()
    profile = json.loads(smoke.synthetic_profile())
    assert profile["rules"] == ["MATCH,DIRECT"]
    assert profile["proxy-groups"] == [
        {"name": "Smoke", "type": "select", "proxies": ["DIRECT", "Synthetic"]}
    ]
    assert profile["proxies"][0]["server"] == "203.0.113.1"
    assert "proxy-providers" not in profile
    assert "rule-providers" not in profile
