import copy
from urllib.parse import urlsplit

import pytest
from decky_proxy.configuration import build_config, parse_subscription
from decky_proxy.errors import ProxyError

YAML = """
proxies:
  - name: Tokyo
    type: trojan
    server: example.com
    port: 443
    password: test-only
    udp: true
"""


def test_import_nodes_and_never_copy_root_control_settings():
    nodes, providers = parse_subscription(YAML + "external-controller: 0.0.0.0:9999\n")
    before = copy.deepcopy(nodes)
    config = build_config(nodes, mode="rule", tun=True, secret="secret")
    assert config["external-controller"] == "127.0.0.1:19791"
    assert config["allow-lan"] is False
    assert config["secret"] == "secret"
    assert "proxy-providers" not in config
    assert config["tun"]["auto-route"] is True
    assert config["tun"]["device"] == "DeckyProxy"
    assert config["tun"]["dns-hijack"] == ["any:53", "tcp://any:53"]
    assert config["rules"][-1] == "MATCH,节点选择"
    assert nodes == before
    assert providers == []


@pytest.mark.parametrize(
    "text", ["", "hello", "proxies: []", "proxies: [1]", "!!python/object:os.system {}"]
)
def test_reject_invalid_or_unsafe_yaml(text):
    with pytest.raises(ProxyError):
        parse_subscription(text)


def test_reject_aliases_and_duplicate_yaml_keys():
    for text in ["proxies: &a [*a]", YAML + "proxies: []\n"]:
        with pytest.raises(ProxyError):
            parse_subscription(text)


@pytest.mark.parametrize("field", ["client-key", "client-certificate", "ca", "private-key"])
def test_reject_file_backed_credentials(field):
    with pytest.raises(ProxyError):
        parse_subscription(YAML + f"    {field}: /etc/shadow\n")


def test_reject_unsupported_proxy_and_duplicate_names():
    with pytest.raises(ProxyError):
        parse_subscription(YAML.replace("trojan", "ssh"))
    with pytest.raises(ProxyError):
        parse_subscription(YAML + YAML.split("proxies:\n")[1])


def test_provider_urls_are_returned_for_python_materialization():
    nodes, providers = parse_subscription(
        "proxy-providers:\n  airport:\n    type: http\n    url: https://example.com/sub\n"
    )
    assert nodes == []
    assert providers == ["https://example.com/sub"]
    with pytest.raises(ProxyError):
        parse_subscription("proxy-providers:\n  bad:\n    type: file\n    path: /etc/shadow\n")


@pytest.mark.parametrize("mode", ["global", "direct", "rule"])
def test_all_modes_have_complete_owned_dns_and_no_remote_assets(mode):
    nodes, _ = parse_subscription(YAML)
    config = build_config(nodes, mode=mode, tun=False, secret="x")
    assert config["mode"] == mode
    assert config["tun"]["enable"] is False
    assert config["mixed-port"] == 19790
    assert config["dns"]["enable"] is True
    assert not any(rule.startswith(("GEOIP", "GEOSITE", "RULE-SET")) for rule in config["rules"])


def test_empty_and_invalid_mode_rejected():
    with pytest.raises(ProxyError):
        build_config([], mode="rule", tun=True, secret="x")
    with pytest.raises(ProxyError):
        build_config([{}], mode="invalid", tun=True, secret="x")


def test_update_downloads_resolve_real_public_addresses_while_tun_is_enabled():
    from decky_proxy.update_manifest import MANIFEST_URL, MIRRORS

    nodes, _ = parse_subscription(YAML)
    config = build_config(nodes, mode="rule", tun=True, secret="x")
    filters = set(config["dns"]["fake-ip-filter"])
    hosts = {urlsplit(prefix + MANIFEST_URL).hostname for prefix in MIRRORS}
    hosts |= {"api.github.com", "release-assets.githubusercontent.com",
              "objects.githubusercontent.com", "raw.githubusercontent.com"}
    assert hosts <= filters
    assert "*" not in filters
    assert config["dns"]["enhanced-mode"] == "fake-ip"
    assert config["profile"]["store-fake-ip"] is False
