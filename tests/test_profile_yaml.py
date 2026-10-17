"""YAML graph limits apply before merge flattening can allocate expanded lists."""
import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.profile_yaml import UniqueLoader, load_yaml


def merge_chain(levels: int, width: int = 2) -> str:
    value = "a0: &a0 {key: 1}\n"
    for index in range(1, levels + 1):
        aliases = ", ".join([f"*a{index - 1}"] * width)
        value += f"a{index}: &a{index} {{<<: [{aliases}]}}\n"
    return value


def test_merge_alias_bomb_is_rejected_before_constructing_any_object(monkeypatch):
    def forbidden_construct(self, node):
        raise AssertionError("unsafe graph reached YAML object construction")

    monkeypatch.setattr(UniqueLoader, "construct_document", forbidden_construct)
    with pytest.raises(ProxyError):
        load_yaml(merge_chain(18))


def test_merge_expanded_budget_is_enforced_before_flattening(monkeypatch):
    monkeypatch.setattr("decky_proxy.profile_yaml.MAX_TREE_ITEMS", 400)
    with pytest.raises(ProxyError):
        load_yaml(merge_chain(4, width=5))


def test_small_merge_chains_and_explicit_overrides_still_work():
    value = load_yaml(merge_chain(3) + "last: {<<: *a3, key: 2, extra: ok}\n")
    assert value["a3"] == {"key": 1}
    assert value["last"] == {"key": 2, "extra": "ok"}


def test_recursive_merge_is_rejected_before_flattening(monkeypatch):
    def forbidden_flatten(self, node):
        raise AssertionError("recursive graph reached merge flattening")

    monkeypatch.setattr(UniqueLoader, "flatten_mapping", forbidden_flatten)
    with pytest.raises(ProxyError):
        load_yaml("recursive: &recursive {<<: *recursive}\n")
