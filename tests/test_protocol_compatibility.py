"""Synthetic complete profiles cover protocols used by ordinary Mihomo YAML."""
import base64
import copy
import json

import pytest
from decky_proxy.configuration import build_config, prepare_profile, validate_nodes
from decky_proxy.errors import ProxyError
from decky_proxy.safe_regex import filter_match

KEY = base64.b64encode(bytes(range(32))).decode()
ANYTLS = {"name": "Secure", "type": "anytls", "server": "example.com", "port": 443,
          "password": "test-only", "sni": "example.org", "skip-cert-verify": False}
WG = {"name": "Tunnel", "type": "wireguard", "server": "example.net", "port": 51820,
      "ip": "192.0.2.2", "ipv6": "2001:db8::2", "private-key": KEY, "public-key": KEY,
      "reserved": [1, 2, 3], "dns": ["1.1.1.1"], "mtu": 1280, "udp": True}


def prepare(value: dict) -> dict:
    return prepare_profile(json.dumps(value), lambda url: b"")


def test_preserves_anytls_wireguard_and_node_chains_without_mutation():
    value = {"proxies": [ANYTLS, {**WG, "dialer-proxy": "Secure"}],
             "proxy-groups": [{"name": "Service", "type": "select",
                               "proxies": ["Tunnel", "Secure", "DIRECT"]}],
             "rules": ["IP-ASN,13335,Service,no-resolve", "MATCH,Service"]}
    before = copy.deepcopy(value)
    profile = prepare(value)
    config = build_config(profile, mode="rule", tun=True, secret="owned")
    assert config["proxies"] == value["proxies"]
    assert config["proxy-groups"] == value["proxy-groups"]
    assert config["rules"] == value["rules"]
    assert value == before


@pytest.mark.parametrize("patch", [
    {"private-key": "/etc/shadow"}, {"private-key": "invalid"},
    {"private-key": base64.b64encode(b"short").decode()}, {"public-key": "invalid"},
    {"pre-shared-key": "/tmp/key"}, {"private-key-file": "/tmp/key"},
    {"reserved": [0, 1, 256]}, {"reserved": [True, 2, 3]}, {"reserved": [0, 1]},
    {"ip": "example.com"}, {"ip": "2001:db8::1"}, {"ipv6": "192.0.2.1"},
    {"dns": ["https://127.0.0.1/dns-query"]}, {"mtu": 1},
])
def test_wireguard_rejects_invalid_keys_networks_and_local_files(patch):
    with pytest.raises(ProxyError):
        validate_nodes([{**WG, **patch}])


def test_wireguard_peer_form_does_not_require_legacy_endpoint():
    peer_form = {key: value for key, value in WG.items()
                 if key not in ("server", "port", "public-key", "reserved")}
    peer_form["peers"] = [
        {"server": "example.net", "port": 51820, "public-key": KEY,
         "pre-shared-key": KEY, "allowed-ips": ["0.0.0.0/0", "::/0"],
         "reserved": [1, 2, 3]}]
    assert validate_nodes([peer_form]) == [peer_form]


@pytest.mark.parametrize("peer", [
    {"server": "example.net", "port": 51820, "public-key": KEY},
    {"server": "example.net", "port": 51820, "public-key": KEY,
     "allowed-ips": ["broken"]},
    {"server": "example.net", "port": True, "public-key": KEY,
     "allowed-ips": ["0.0.0.0/0"]},
    {"server": "example.net", "port": 51820, "public-key": KEY,
     "private-key": KEY, "allowed-ips": ["0.0.0.0/0"]},
])
def test_wireguard_rejects_invalid_peer_form(peer):
    with pytest.raises(ProxyError):
        validate_nodes([{**WG, "peers": [peer]}])


@pytest.mark.parametrize("patch", [
    {"password": ""}, {"password": 123}, {"password": "bad\nvalue"},
    {"skip-cert-verify": "true"}, {"idle-session-timeout": -1},
    {"idle-session-check-interval": True}, {"min-idle-session": 10000},
    {"alpn": [123]}, {"private-key": KEY}, {"certificate": "/tmp/cert"},
])
def test_anytls_rejects_invalid_options_and_file_backed_client_keys(patch):
    with pytest.raises(ProxyError):
        validate_nodes([{**ANYTLS, **patch}])


@pytest.mark.parametrize("nodes,groups", [
    ([{**ANYTLS, "dialer-proxy": "missing"}], []),
    ([{**ANYTLS, "dialer-proxy": "Secure"}], []),
    ([{**ANYTLS, "dialer-proxy": "Tunnel"}, {**WG, "dialer-proxy": "Secure"}], []),
    ([{**ANYTLS, "dialer-proxy": "Service"}],
     [{"name": "Service", "type": "select", "proxies": ["Secure"]}]),
])
def test_dialer_graph_rejects_missing_targets_and_cycles(nodes, groups):
    with pytest.raises(ProxyError):
        prepare({"proxies": nodes, "proxy-groups": groups})


def test_dialer_can_use_acyclic_group_or_direct():
    nodes = [{**ANYTLS, "dialer-proxy": "Service"}, {**WG, "dialer-proxy": "DIRECT"}]
    groups = [{"name": "Service", "type": "select", "proxies": ["Tunnel", "DIRECT"]}]
    assert prepare({"proxies": nodes, "proxy-groups": groups})["nodes"] == nodes


def test_dialer_cycle_through_provider_membership_rejected():
    value = {"proxy-providers": {"Remote": {"type": "inline", "payload": [
        {**ANYTLS, "dialer-proxy": "Service"}]}},
        "proxy-groups": [{"name": "Service", "type": "select", "use": ["Remote"]}]}
    with pytest.raises(ProxyError, match="循环引用"):
        prepare(value)


def test_dialer_group_including_all_nodes_cannot_contain_its_own_dialer():
    with pytest.raises(ProxyError, match="循环引用"):
        prepare({"proxies": [{**ANYTLS, "dialer-proxy": "Service"}],
                 "proxy-groups": [{"name": "Service", "type": "select", "include-all": True}]})


def test_integer_expected_status_in_yaml_normalized_for_mihomo():
    profile = prepare({"proxies": [ANYTLS], "proxy-groups": [
        {"name": "Service", "type": "url-test", "proxies": ["Secure"],
         "expected-status": 204}]})
    assert profile["groups"][0]["expected-status"] == "204"


def test_72_rule_providers_and_rules_retained():
    sources = {f"Rules{i}": {"type": "inline", "behavior": "domain",
                            "payload": [f"+.site{i}.example"]} for i in range(72)}
    rules = [f"RULE-SET,{name},DIRECT" for name in sources]
    profile = prepare({"proxies": [ANYTLS], "rule-providers": sources, "rules": rules})
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    assert len(config["rule-providers"]) == 72
    assert config["rules"] == rules


def test_128_rule_provider_cap_is_explicit_and_129_rejected():
    providers = {f"Rules{i}": {"type": "inline", "behavior": "domain",
                              "payload": [f"+.site{i}.example"]} for i in range(128)}
    profile = prepare({"proxies": [ANYTLS], "rule-providers": providers})
    assert len(profile["provider_files"]) == 128
    assert len(build_config(profile, mode="rule", tun=False, secret="owned")[
        "rule-providers"]) == 128
    with pytest.raises(ProxyError, match="128"):
        prepare({"proxies": [ANYTLS], "rule-providers": {
            **providers, "TooMany": providers["Rules0"]}})


@pytest.mark.parametrize("rule", ["IP-ASN,4294967295,DIRECT", "SRC-IP-ASN,13335,DIRECT"])
def test_asn_rule_supported(rule):
    assert prepare({"proxies": [ANYTLS], "rules": [rule]})["rules"] == [rule]


@pytest.mark.parametrize("asn", ["-1", "4294967296", "1.5", "/tmp/asn", "AS13335"])
def test_invalid_asn_rejected(asn):
    with pytest.raises(ProxyError):
        prepare({"proxies": [ANYTLS], "rules": [f"IP-ASN,{asn},DIRECT"]})


@pytest.mark.parametrize("user_agent", ["clash.meta", "ClashMeta/v1.0.0"])
def test_safe_user_agent_provider_uses_clash_downloader_and_preserves_filter(user_agent):
    called = []

    def download(url: str) -> bytes:
        called.append(url)
        return json.dumps({"proxies": [ANYTLS]}).encode()

    profile = prepare_profile(json.dumps({"proxy-providers": {"Remote": {
        "type": "http", "url": "https://example.com/nodes", "proxy": "DIRECT",
        "header": {"User-Agent": [user_agent]}, "exclude-filter": "Unavailable"}},
        "proxy-groups": [{"name": "Service", "type": "select", "use": ["Remote"]}]}),
        download)
    assert called == ["https://example.com/nodes"]
    normalized = profile["proxy_providers"]["Remote"]["exclude-filter"]
    assert not filter_match(normalized, "Secure")
    assert "header" not in profile["proxy_providers"]["Remote"]
    assert build_config(profile, mode="rule", tun=False, secret="owned")[
        "proxy-providers"]["Remote"]["exclude-filter"] == normalized


@pytest.mark.parametrize("provider", [
    {"header": {"Authorization": ["test-only"]}},
    {"header": {"User-Agent": ["clash\r\nInjected: true"]}},
    {"header": {"User-Agent": "not-a-list"}},
    {"header": {"User-Agent": ["nonclash-agent"]}},
    {"proxy": "Service"},
])
def test_unsupported_provider_headers_and_route_proxy_reported(provider):
    with pytest.raises(ProxyError):
        prepare_profile(json.dumps({"proxy-providers": {"Remote": {
            "type": "http", "url": "https://example.com/nodes", **provider}}}),
            lambda url: json.dumps({"proxies": [ANYTLS]}).encode())


@pytest.mark.parametrize("payload,behavior,entries", [
    (b"payload:\n- exact.example\n- +.suffix.example\n", "domain",
     ["exact.example", "+.suffix.example"]),
    (b"# ordinary text list\nDOMAIN-SUFFIX,example.org\nIP-CIDR,192.0.2.0/24\n", "classical",
     ["DOMAIN-SUFFIX,example.org", "IP-CIDR,192.0.2.0/24"]),
])
def test_mislabeled_rule_provider_is_normalized_without_losing_entries(payload, behavior, entries):
    import yaml

    profile = prepare_profile(json.dumps({"proxies": [ANYTLS], "rule-providers": {"Rules": {
        "type": "http", "url": "https://example.com/rules", "behavior": "classical"}},
        "rules": ["RULE-SET,Rules,DIRECT"]}), lambda url: payload)
    provider = profile["rule_providers"]["Rules"]
    stored = base64.b64decode(profile["provider_files"][provider["path"]])
    assert provider["behavior"] == behavior
    assert provider["format"] == "yaml"
    assert yaml.safe_load(stored)["payload"] == entries
    assert profile["normalized_rule_providers"] == 1
    assert build_config(profile, mode="rule", tun=False, secret="owned")[
        "rule-providers"]["Rules"]["behavior"] == behavior


@pytest.mark.parametrize("payload", [
    b"payload: [example.org, 'DOMAIN,example.net']",
    b"payload: ['/etc/shadow']", b"payload: ['https://example.com']",
    b"payload: ['example.org:443']", b"payload: ['bad..example']",
    b"DOMAIN,example.org\nINVALID,example.net\n",
    b"payload: [DOMAIN,example.org\n",
])
def test_rule_provider_inference_never_hides_mixed_or_invalid_rules(payload):
    with pytest.raises(ProxyError):
        prepare_profile(json.dumps({"proxies": [ANYTLS], "rule-providers": {"Rules": {
            "type": "http", "url": "https://example.com/rules", "behavior": "classical"}}}),
            lambda url: payload)


def test_classical_provider_accepts_mihomo_ignored_policy_parameter_without_rewriting():
    payload = b"DOMAIN-SUFFIX,example.org,reject\nIP-CIDR,192.0.2.0/24,DIRECT,no-resolve\n"
    profile = prepare_profile(json.dumps({"proxies": [ANYTLS], "rule-providers": {"Rules": {
        "type": "http", "url": "https://example.com/rules", "behavior": "classical",
        "format": "text"}}}), lambda url: payload)
    provider = profile["rule_providers"]["Rules"]
    assert base64.b64decode(profile["provider_files"][provider["path"]]) == payload
