"""Filters are bounded before root use and shape the actual dialing graph."""
import json

import pytest
from decky_proxy.configuration import build_config, prepare_profile
from decky_proxy.errors import ProxyError
from decky_proxy.safe_regex import filter_match

NODE_A = {"name": "A", "type": "anytls", "server": "example.org", "port": 443,
          "password": "test-only", "dialer-proxy": "Group"}
NODE_B = {"name": "B", "type": "trojan", "server": "example.net", "port": 443,
          "password": "test-only"}


def prepare(value: dict) -> dict:
    return prepare_profile(json.dumps(value), lambda url: b"")


@pytest.mark.parametrize("key", ["filter", "exclude-filter"])
def test_nested_quantifier_group_filters_are_frozen_before_core_use(key):
    nodes = [{**NODE_B, "name": "aa"}, NODE_B]
    profile = prepare({"proxies": nodes, "proxy-groups": [
        {"name": "Group", "type": "select", "include-all-proxies": True, key: "(a+)+$"}]})
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    expression = config["proxy-groups"][0][key]
    assert expression != "(a+)+$"
    assert filter_match(expression, "aa")
    assert not filter_match(expression, "B")


@pytest.mark.parametrize("key", ["filter", "exclude-filter"])
def test_nested_quantifier_provider_filters_are_frozen_before_core_use(key):
    profile = prepare({"proxy-providers": {"Remote": {
        "type": "inline", "payload": [{**NODE_B, "name": "aa"}, NODE_B], key: "(a+)+$"}},
        "proxy-groups": [{"name": "Group", "type": "select", "use": ["Remote"]}]})
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    expression = config["proxy-providers"]["Remote"][key]
    assert expression != "(a+)+$"
    assert filter_match(expression, "aa")
    assert not filter_match(expression, "B")


@pytest.mark.parametrize("settings", [
    {"filter": "^B$"}, {"exclude-filter": "^A$"}, {"exclude-type": "AnyTLS"},
    {"filter": "^missing$`^B$"},
])
def test_include_all_inline_graph_honors_real_filter_membership(settings):
    value = {"proxies": [NODE_A, NODE_B], "proxy-groups": [
        {"name": "Group", "type": "select", "include-all-proxies": True, **settings}]}
    profile = prepare(value)
    assert build_config(profile, mode="rule", tun=False, secret="owned")["proxies"] == [
        NODE_A, NODE_B]


def test_group_filter_does_not_hide_explicit_proxy_cycle():
    with pytest.raises(ProxyError, match="循环引用"):
        prepare({"proxies": [NODE_A, NODE_B], "proxy-groups": [
            {"name": "Group", "type": "select", "proxies": ["A"], "filter": "^B$"}]})


def test_include_all_inline_does_not_accidentally_include_provider_nodes():
    profile = prepare({"proxies": [NODE_B], "proxy-providers": {"Remote": {
        "type": "inline", "payload": [NODE_A]}}, "proxy-groups": [
        {"name": "Group", "type": "select", "include-all-proxies": True}]})
    assert len(profile["nodes"]) == 2


@pytest.mark.parametrize("provider_settings,group_settings", [
    ({"filter": "^B$"}, {}), ({"exclude-filter": "^A$"}, {}),
    ({"exclude-type": "anytls"}, {}), ({}, {"filter": "^B$"}),
    ({}, {"exclude-filter": "^A$"}), ({}, {"exclude-type": "AnyTLS"}),
])
def test_provider_and_group_filters_remove_false_dialer_cycles(provider_settings, group_settings):
    profile = prepare({"proxy-providers": {"Remote": {
        "type": "inline", "payload": [NODE_A, NODE_B], **provider_settings}},
        "proxy-groups": [{"name": "Group", "type": "select", "use": ["Remote"],
                          **group_settings}]})
    assert len(profile["nodes"]) == 2


def test_group_exclusion_removes_explicit_group_cycle():
    profile = prepare({"proxies": [NODE_B], "proxy-groups": [
        {"name": "Group", "type": "select", "proxies": ["Other", "B"],
         "exclude-filter": "^Other$"},
        {"name": "Other", "type": "select", "proxies": ["Group"]}]})
    assert len(profile["groups"]) == 2


def test_group_exclude_type_uses_mihomo_runtime_type_names():
    profile = prepare({"proxies": [NODE_B], "proxy-groups": [
        {"name": "Group", "type": "select", "proxies": ["Other", "B"],
         "exclude-type": "selector"},
        {"name": "Other", "type": "select", "proxies": ["Group"]}]})
    assert len(profile["groups"]) == 2


def test_unsafe_stored_group_filter_revalidated_at_startup():
    node = {**NODE_B, "name": "a" * 100 + "!"}
    profile = prepare({"proxies": [node], "proxy-groups": [
        {"name": "Group", "type": "select", "proxies": [node["name"]]}]})
    modified = {**profile, "groups": [{**profile["groups"][0], "filter": "(a+)+$"}]}
    with pytest.raises(ProxyError, match="超时|资源"):
        build_config(modified, mode="rule", tun=False, secret="owned")
    assert "filter" not in profile["groups"][0]


def test_unsafe_stored_provider_filter_revalidated_at_startup():
    node = {**NODE_B, "name": "a" * 100 + "!"}
    profile = prepare({"proxy-providers": {"Remote": {"type": "inline", "payload": [node]}}})
    modified = {**profile, "proxy_providers": {"Remote": {
        **profile["proxy_providers"]["Remote"], "exclude-filter": "(a+)+$"}}}
    with pytest.raises(ProxyError, match="超时|资源"):
        build_config(modified, mode="rule", tun=False, secret="owned")
    assert "exclude-filter" not in profile["proxy_providers"]["Remote"]


def test_complex_source_filter_still_detects_real_dialer_cycles():
    with pytest.raises(ProxyError, match="循环引用"):
        prepare({"proxies": [NODE_A, NODE_B], "proxy-groups": [
            {"name": "Group", "type": "select", "include-all-proxies": True,
             "filter": "^(?:(?!B).)*$"}]})


def test_bounded_composite_filter_becomes_equivalent_literal_membership():
    expression = "^(?:Beta|B)?$"
    profile = prepare({"proxies": [NODE_A, NODE_B], "proxy-groups": [
        {"name": "Group", "type": "select", "include-all-proxies": True,
         "filter": expression}]})
    normalized = profile["groups"][0]["filter"]
    assert normalized != expression
    assert filter_match(normalized, "B")
    assert not filter_match(normalized, "A")
    assert build_config(profile, mode="rule", tun=False, secret="owned")[
        "proxy-groups"][0]["include-all-proxies"]


def test_large_canonical_filter_revalidates_in_stored_provider_and_group():
    nodes = [{**NODE_B, "name": f"SyntheticNode{index:03d}"} for index in range(100)]
    profile = prepare({"proxy-providers": {"Remote": {"type": "inline", "payload": nodes,
        "filter": "^(?:SyntheticNode[0-9]{3})?$"}}, "proxy-groups": [
        {"name": "Group", "type": "select", "use": ["Remote"]}]})
    assert len(profile["proxy_providers"]["Remote"]["filter"]) > 1024
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    assert config["proxy-providers"]["Remote"]["filter"] == profile[
        "proxy_providers"]["Remote"]["filter"]


def test_default_group_does_not_forward_nodes_removed_by_provider_filters():
    excluded = {**NODE_A, "dialer-proxy": "Missing"}
    profile = prepare({"proxy-providers": {"Remote": {
        "type": "inline", "payload": [excluded, NODE_B], "filter": "^B$"}}})
    assert len(profile["nodes"]) == 2  # Preserve the source snapshot privately.
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    assert config["proxies"] == [NODE_B]
    assert config["proxy-groups"][1]["proxies"] == ["B"]


def test_default_group_rejects_unfiltered_dialer_cycles():
    with pytest.raises(ProxyError, match="循环引用"):
        prepare({"proxy-providers": {"Remote": {"type": "inline", "payload": [
            {**NODE_A, "dialer-proxy": "B"}, {**NODE_B, "dialer-proxy": "A"}]}}})


def test_unicode_engine_differences_cannot_bypass_the_dialer_graph():
    name = "A\u0301"  # Python and regexp2 differ on combining marks in \w.
    profile = prepare({"proxies": [{**NODE_A, "name": name}, NODE_B], "proxy-groups": [
        {"name": "Group", "type": "select", "include-all-proxies": True,
         "filter": r"^\w+$"}]})
    config = build_config(profile, mode="rule", tun=False, secret="owned")
    normalized = config["proxy-groups"][0]["filter"]
    assert normalized != r"^\w+$"
    assert "\\w" not in normalized
    assert not filter_match(normalized, name)
    assert filter_match(normalized, "B")


def test_stored_provider_source_filter_is_canonicalized_before_forwarding():
    name = "A\u0301"
    profile = prepare({"proxy-providers": {"Remote": {"type": "inline", "payload": [
        {**NODE_A, "name": name}, NODE_B], "filter": "^B$"}}, "proxy-groups": [
        {"name": "Group", "type": "select", "use": ["Remote"]}]})
    changed = {**profile, "proxy_providers": {"Remote": {
        **profile["proxy_providers"]["Remote"], "filter": r"^\w+$"}}}
    config = build_config(changed, mode="rule", tun=False, secret="owned")
    normalized = config["proxy-providers"]["Remote"]["filter"]
    assert normalized != r"^\w+$"
    assert not filter_match(normalized, name)
