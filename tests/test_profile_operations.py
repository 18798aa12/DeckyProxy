import copy

import pytest
from decky_proxy.errors import ProxyError

from tests.test_configuration import YAML

FULL = (
    YAML
    + """
proxy-groups:
  - name: MyPolicy
    type: select
    proxies: [Tokyo, DIRECT]
rules:
  - DOMAIN-SUFFIX,example.org,MyPolicy
  - MATCH,DIRECT
"""
)


async def test_full_configuration_keeps_rules_groups_and_safe_summary(service):
    state = await service.import_profile("full", "", FULL)
    summary = state["active_profile_summary"]
    assert summary["source_rules"] and not summary["legacy"]
    assert summary["rules"] == 2 and summary["groups"] == 1
    assert summary["normalized_rule_providers"] == 0
    await service.start_proxy()
    assert service.core.config["rules"] == ["DOMAIN-SUFFIX,example.org,MyPolicy", "MATCH,DIRECT"]
    assert service.core.config["proxy-groups"][0]["name"] == "MyPolicy"


async def test_summary_reports_ruleset_format_corrections(service):
    service.download = lambda _: b"payload: [example.org, +.example.net]"
    state = await service.import_profile(
        "normalized", "", FULL + """
rule-providers:
  domains:
    type: http
    url: https://example.com/rules
    behavior: classical
"""
    )
    assert state["active_profile_summary"]["normalized_rule_providers"] == 1


async def test_custom_rules_survive_subscription_refresh_and_failed_download(service):
    service.download = lambda url: FULL.encode() if "sub" in url else b"payload: [+.example.net]"
    original = await service.import_profile("full", "https://example.com/sub", "")
    key = original["active_profile_id"]
    result = await service.import_rule_provider(
        "Extra", "https://example.com/rules", "domain", "yaml", "MyPolicy"
    )
    assert result["active_profile_summary"]["rule_providers"] == 1
    before = copy.deepcopy(service.store.read_profile(key))
    await service.refresh_profile(key)
    await service.start_proxy()
    assert service.core.config["rules"][-2:] == ["RULE-SET,Extra,MyPolicy", "MATCH,DIRECT"]
    service.download = lambda _: b"not a ruleset"
    with pytest.raises(ProxyError):
        await service.refresh_profile(key)
    assert service.store.read_profile(key) == before
    assert (await service.get_status())["running"]


async def test_legacy_configuration_still_starts_and_prompts_refresh(service):
    state = await service.import_profile("old", "", YAML)
    key = state["active_profile_id"]
    stored = service.store.read_profile(key)
    service.store.write_profile(key, {"nodes": stored["nodes"], "url": ""})
    assert (await service.get_status())["active_profile_summary"]["legacy"]
    assert (await service.start_proxy())["running"]


async def test_ruleset_core_validation_failure_retains_profile_and_running_state(service):
    state = await service.import_profile("full", "", FULL)
    key = state["active_profile_id"]
    await service.start_proxy()
    previous = service.store.read_profile(key)
    service.download = lambda _: b"payload: [+.example.net]"
    service.core.fail_validate = True
    with pytest.raises(ProxyError):
        await service.import_rule_provider(
            "Extra", "https://example.com/r", "domain", "yaml", "MyPolicy"
        )
    assert service.store.read_profile(key) == previous
    assert service.core.running


async def test_profile_downloads_share_a_total_budget(service):
    # An oversized injected transport result must never be parsed or persisted.
    service.download = lambda _: b"x" * (33 * 1024 * 1024)
    with pytest.raises(ProxyError, match="限制"):
        await service.import_profile("large", "https://example.com/sub", "")
    assert not (await service.get_status())["profiles"]


async def test_provider_budget_stops_starting_more_downloads(service, monkeypatch):
    import json

    monkeypatch.setattr("decky_proxy.profile_operations.MAX_IMPORT_BYTES", len(YAML.encode()) + 10)
    calls = []

    def download(url):
        calls.append(url)
        return YAML.replace("Tokyo", "Node" + str(len(calls))).encode()

    service.download = download
    content = json.dumps(
        {
            "proxy-providers": {
                str(i): {"type": "http", "url": f"https://example.com/{i}"} for i in range(4)
            }
        }
    )
    with pytest.raises(ProxyError, match="限制"):
        await service.import_profile("budget", "", content)
    assert len(calls) == 2


async def test_refresh_prunes_obsolete_cache_after_success_and_validation_failure(service):
    state = await service.import_profile("full", "", FULL)
    key = state["active_profile_id"]
    service.download = lambda _: b"payload: [+.example.net]"
    await service.import_rule_provider(
        "Extra", "https://example.com/r", "domain", "yaml", "MyPolicy"
    )
    before = set((service.runtime / "providers").iterdir())
    service.download = lambda _: b"payload: [+.example.org]"
    await service.refresh_profile(key)
    after = set((service.runtime / "providers").iterdir())
    assert len(after) == 1 and not (before & after)
    service.core.fail_validate = True
    service.download = lambda _: b"payload: [+.example.com]"
    with pytest.raises(ProxyError):
        await service.refresh_profile(key)
    assert set((service.runtime / "providers").iterdir()) == after


async def test_asn_rules_are_preserved_for_offline_database(service):
    state = await service.import_profile(
        "asn", "", FULL.replace("DOMAIN-SUFFIX,example.org", "IP-ASN,123")
    )
    profile = service.store.read_profile(state["active_profile_id"])
    assert profile["rules"][0] == "IP-ASN,123,MyPolicy"
