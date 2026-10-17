"""Full-profile imports retain routing without trusting privileged root settings."""
import base64
import copy
import json

import pytest
from decky_proxy.configuration import (
    build_config,
    prepare_profile,
    prepare_rule_provider,
    write_provider_files,
)
from decky_proxy.errors import ProxyError

NODE = {"name": "Tokyo", "type": "trojan", "server": "example.com", "port": 443,
        "password": "test-only"}
PROFILE = {"proxies": [NODE], "proxy-groups": [
    {"name": "Service", "type": "select", "proxies": ["Tokyo", "DIRECT"]}],
    "rules": ["DOMAIN-SUFFIX,example.org,Service", "MATCH,DIRECT"]}


def prepare(value, download=lambda url: b""):
    return prepare_profile(json.dumps(value), download)


def test_preserves_groups_rules_but_not_unsafe_root_keys():
    original = {**PROFILE, "external-controller": "0.0.0.0:9999", "secret": "untrusted",
                "tun": {"enable": False}}
    before = copy.deepcopy(original)
    profile = prepare(original)
    config = build_config(profile, mode="rule", tun=True, secret="owned")
    assert profile["schema_version"] == 2
    assert profile["source_rules"] is True
    assert config["proxy-groups"] == PROFILE["proxy-groups"]
    assert config["rules"] == PROFILE["rules"]
    assert config["secret"] == "owned"
    assert config["tun"]["enable"]
    assert "script" not in config
    assert original == before


def test_safe_yaml_anchors_and_merge_overrides_work():
    value = """
base: &node {type: trojan, server: example.com, port: 443, password: test-only}
proxies:
  - <<: *node
    name: Tokyo
    port: 8443
proxy-groups:
  - {name: Service, type: select, proxies: [Tokyo, DIRECT]}
rules: ["MATCH,Service"]
"""
    assert prepare_profile(value, lambda url: b"")["nodes"][0]["port"] == 8443


@pytest.mark.parametrize("value", ["proxies: &a [*a]", "a: &a [*a]", "x: 1\nx: 2"])
def test_rejects_cycles_and_duplicate_yaml(value):
    with pytest.raises(ProxyError):
        prepare_profile(value, lambda url: b"")


def test_rejects_excessively_expanded_aliases():
    value = "a: &a [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]\n"
    for level in range(1, 7):
        previous, current = chr(96 + level), chr(97 + level)
        value += current + ": &" + current + " [" + ",".join(["*" + previous] * 10) + "]\n"
    with pytest.raises(ProxyError):
        prepare_profile(value, lambda url: b"")


@pytest.mark.parametrize("groups", [
    [{"name": "Service", "type": "select", "proxies": ["missing"]}],
    [{"name": "Service", "type": "select", "proxies": ["Service"]}],
    [{"name": "A", "type": "select", "proxies": ["B"]},
     {"name": "B", "type": "select", "proxies": ["A"]}],
    [{"name": "DIRECT", "type": "select", "proxies": ["Tokyo"]}],
])
def test_rejects_unknown_references_and_group_cycles(groups):
    with pytest.raises(ProxyError):
        prepare({**PROFILE, "proxy-groups": groups})


@pytest.mark.parametrize("rule", ["MATCH,missing", "RULE-SET,absent,DIRECT",
                                  "GEOSITE,/etc/shadow,DIRECT", "SUB-RULE,x,y",
                                  "UNKNOWN,x,DIRECT"])
def test_rejects_unsupported_or_missing_rule_references(rule):
    with pytest.raises(ProxyError):
        prepare({**PROFILE, "rules": [rule]})


def test_remote_and_inline_proxy_providers_preserve_group_membership():
    second = {**NODE, "name": "Osaka"}
    profile = prepare({"proxy-providers": {
        "Remote": {"type": "http", "url": "https://example.com/nodes", "path": "/etc/shadow"},
        "Inline": {"type": "inline", "payload": [second]}},
        "proxy-groups": [{"name": "Service", "type": "select", "use": ["Remote", "Inline"]}],
        "rules": ["MATCH,Service"]}, lambda url: json.dumps({"proxies": [NODE]}).encode())
    assert [node["name"] for node in profile["nodes"]] == ["Tokyo", "Osaka"]
    assert profile["inline_nodes"] == []
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    assert config["proxies"] == []
    assert config["proxy-groups"][0]["use"] == ["Remote", "Inline"]
    assert all(provider["type"] == "file" for provider in config["proxy-providers"].values())
    assert all("url" not in provider for provider in config["proxy-providers"].values())
    assert all(path.startswith("providers/") for path in profile["provider_files"])


@pytest.mark.parametrize("behavior,format,payload", [
    ("domain", "yaml", b'payload: ["+.example.org"]'),
    ("domain", "text", b'# comment\n+.example.org\n'),
    ("ipcidr", "text", b'192.0.2.0/24\n'),
    ("classical", "yaml", b'payload: ["DOMAIN-SUFFIX,example.org"]'),
])
def test_rule_provider_formats_materialize(behavior, format, payload):
    profile = prepare({**PROFILE, "rule-providers": {"Rules": {
        "type": "http", "url": "https://example.com/rules", "behavior": behavior,
        "format": format, "path": "/etc/shadow"}},
        "rules": ["RULE-SET,Rules,Service", "MATCH,DIRECT"]}, lambda url: payload)
    provider = profile["rule_providers"]["Rules"]
    assert provider["type"] == "file"
    assert provider["format"] == format
    written = base64.b64decode(profile["provider_files"][provider["path"]])
    if format == "yaml":
        assert written.startswith(b"payload:\n-")
        assert written != payload  # Mihomo requires block YAML, including for flow/JSON input.
    else:
        assert written == payload


def test_inline_rule_providers_and_nested_logic_are_validated():
    profile = prepare({**PROFILE, "rule-providers": {"Rules": {
        "type": "inline", "behavior": "domain", "payload": ["+.example.org"]}},
        "rules": ["AND,((DOMAIN-SUFFIX,example.org),(NETWORK,tcp)),Service",
                  "RULE-SET,Rules,DIRECT", "MATCH,Service"]})
    assert profile["rule_providers"]["Rules"]["type"] == "file"
    assert len(profile["rules"]) == 3


def test_custom_rule_inserted_before_first_match_and_preserved_for_refresh():
    profile = prepare(PROFILE)
    result = prepare_rule_provider("Extra", "https://example.com/rules", "domain", "text",
                                   "Service", profile, lambda url: b"+.example.org\n")
    assert result["rules"] == [PROFILE["rules"][0], "RULE-SET,Extra,Service", "MATCH,DIRECT"]
    assert result["custom_rule_sources"][0] == {
        "name": "Extra", "url": "https://example.com/rules", "behavior": "domain",
        "format": "text", "target": "Service"}
    assert "Extra" not in profile["rule_providers"]


@pytest.mark.parametrize("provider", [
    {"type": "file", "path": "/etc/shadow", "behavior": "domain"},
    {"type": "http", "url": "http://example.com/rules", "behavior": "domain"},
    {"type": "http", "url": "https://127.0.0.1/rules", "behavior": "domain"},
    {"type": "inline", "behavior": "classical", "format": "mrs", "payload": []},
    {"type": "inline", "behavior": "domain", "payload": [123]},
])
def test_unsafe_providers_are_rejected(provider):
    with pytest.raises(ProxyError):
        prepare({**PROFILE, "rule-providers": {"Unsafe": provider}})


def test_writes_private_hash_addressed_files_and_rejects_tampered_paths(tmp_path):
    profile = prepare({**PROFILE, "rule-providers": {"Rules": {
        "type": "inline", "behavior": "domain", "payload": ["+.example.org"]}}})
    write_provider_files(profile, tmp_path)
    for path, value in profile["provider_files"].items():
        output = tmp_path / path
        assert output.read_bytes() == base64.b64decode(value)
        assert output.stat().st_mode & 0o777 == 0o600
    for invalid in ("../../escape", "/tmp/escape", "providers/file.yaml"):
        with pytest.raises(ProxyError):
            write_provider_files({**profile, "provider_files": {invalid: "eA=="}}, tmp_path)


def test_provider_symlink_never_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "providers").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProxyError):
        write_provider_files(prepare(PROFILE), runtime)
    assert not list(outside.iterdir())


def test_legacy_list_fallback_unchanged_and_geodata_owned():
    profile = prepare({"proxies": [NODE]})
    assert not profile["source_rules"]
    config = build_config(profile, mode="rule", tun=True, secret="owned")
    assert config["rules"][-1] == "MATCH,节点选择"
    assert config["geo-auto-update"] is False
    assert config["geodata-mode"] is True


def test_custom_provider_refresh_replaces_same_source_without_order_change():
    profile = prepare_rule_provider("Extra", "https://example.com/one", "domain", "text",
                                    "Service", prepare(PROFILE), lambda url: b"+.one.example\n")
    old_files = set(profile["provider_files"])
    profile = prepare_rule_provider("Later", "https://example.com/two", "domain", "text",
                                    "DIRECT", profile, lambda url: b"+.two.example\n")
    result = prepare_rule_provider("Extra", "https://example.com/new", "domain", "text",
                                   "DIRECT", profile, lambda url: b"+.new.example\n")
    assert result["rules"] == [PROFILE["rules"][0], "RULE-SET,Extra,DIRECT",
                               "RULE-SET,Later,DIRECT", "MATCH,DIRECT"]
    assert [source["name"] for source in result["custom_rule_sources"]] == ["Extra", "Later"]
    assert result["custom_rule_sources"][0]["url"] == "https://example.com/new"
    assert not old_files & set(result["provider_files"])


def test_custom_provider_cannot_replace_subscription_rule_provider():
    profile = prepare({**PROFILE, "rule-providers": {"Rules": {
        "type": "inline", "behavior": "domain", "payload": ["+.example.org"]}}})
    with pytest.raises(ProxyError):
        prepare_rule_provider("Rules", "https://example.com/rules", "domain", "text",
                              "DIRECT", profile, lambda url: b"+.new.example\n")


@pytest.mark.parametrize("extra", [{"script": {"code": "unsupported"}},
                                   {"sub-rules": {"extra": ["MATCH,DIRECT"]}}])
def test_unsupported_script_and_subrules_reported(extra):
    with pytest.raises(ProxyError):
        prepare({**PROFILE, **extra})


def test_inline_yaml_rule_provider_is_written_as_mihomo_block_payload():
    profile = prepare({**PROFILE, "rule-providers": {"Rules": {
        "type": "inline", "behavior": "domain", "payload": ["+.example.org"]}}})
    provider = profile["rule_providers"]["Rules"]
    assert base64.b64decode(profile["provider_files"][provider["path"]]) == (
        b"payload:\n- +.example.org\n")
