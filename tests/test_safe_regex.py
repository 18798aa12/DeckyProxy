import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.safe_regex import filter_match, normalize_filters, validate_filter


@pytest.mark.parametrize(
    "pattern",
    [
        "", "日本|香港|🇯🇵", "^B$", "(?i)hk|hong kong", "(?im:^jp$)",
        "^(?!.*(bad|广告)).*(JP|日本)$", "[A-Z0-9_-]+", r"\bJP\b",
        "(a){2}", "a{128}", "a{1,128}", "a*|b+", "(ab|cd)",
        "(?=a)(?!b)(?=c)(?!d).*", "a*(b|cd)",
    ],
)
def test_common_bounded_filters_are_preserved(pattern):
    assert validate_filter(pattern) == pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+$", "(a|aa)+$", "(ab){2}", "a*a*", "a?a?a?a+", "a*(b|c+)",
        "(a{128}){128}", "a{129}", "a{0,129}", "a{129,}", r"(a)\1",
        "(a)?(?(1)b|c)", "(?<=a)b", "(?<!a)b", "(?a)a", "(?u)a", "(?L)a",
        "(?i-u:a)", "(?>a)", "a++", "(?=(?=.*a).*b).*c", "(?=a)" * 5,
        "(" * 9 + "a" + ")" * 9, "a" * 1025, "a" * 257,
        "(?<name>a)", "[", r"\p{L}",
    ],
)
def test_rejects_unsafe_or_incompatible_filters_without_reflection(pattern):
    with pytest.raises(ProxyError) as error:
        validate_filter(pattern)
    assert str(error.value) == "节点筛选表达式过于复杂或不兼容，请简化后重新导入"


@pytest.mark.parametrize("pattern", [None, 1, [], True])
def test_requires_string_pattern(pattern):
    with pytest.raises(ProxyError):
        validate_filter(pattern)


def test_match_validates_before_compiling_or_searching():
    with pytest.raises(ProxyError):
        filter_match("(a+)+$", "a" * 80 + "!")
    assert filter_match("(?i)日本|jp", "🇯🇵 JP 节点")
    assert filter_match("^(?!.*(bad|广告)).*(JP|日本)$", "my日本")
    assert not filter_match("^(?!.*(bad|广告)).*(JP|日本)$", "广告日本")
    assert not filter_match("^B$", "AB")


def test_match_bounds_node_names_and_rejects_non_strings():
    for text in ["a" * 129, None, 1]:
        with pytest.raises(ProxyError):
            filter_match("a+", text)


def test_complex_bounded_filters_are_materialized_before_core_matching():
    patterns = ["(?i)JP", "^(?!.*(bad|广告))(?:JP|日本)(?:-[0-9]+)?$", "(?=(?!bad).*)日本"]
    names = ["JP", "JP-12", "广告日本", "日本", "bad日本", "HK"]
    result = normalize_filters(patterns, names)
    for pattern in patterns:
        assert result[pattern] != pattern
        assert validate_filter(result[pattern]) == result[pattern]
        import re
        assert [filter_match(result[pattern], name) for name in names] == [
            bool(re.search(pattern, name)) for name in names
        ]


def test_empty_filter_keeps_absent_semantics_and_unicode_categories_are_frozen():
    names = ["A\u0301", "A", "日本"]
    result = normalize_filters(["", r"^\w+$"], names)
    assert result[""] == ""
    assert result[r"^\w+$"] != r"^\w+$"
    assert [filter_match(result[r"^\w+$"], name) for name in names] == [False, True, True]


def test_normalization_preserves_backtick_or_and_literal_node_names():
    source = "(?:JP-)?[0-9]+`^(?=(?!bad).*)HK"
    names = ["JP-12", "12", "HK`node", "HK|.*", "badHK", "SG"]
    normalized = normalize_filters([source], names)[source]
    assert "`" not in normalized
    assert [filter_match(normalized, name) for name in names] == [
        True, True, True, True, False, False,
    ]


def test_normalization_empty_matches_and_large_generated_canonical_alternations():
    source = "(?=(?!x).*)^missing$"
    assert normalize_filters([source], ["JP"])[source] == "(?!)"
    names = [f"node-{index}-" + "a" * 100 for index in range(20)]
    result = normalize_filters(["(?=(?!x).*)node"], names)["(?=(?!x).*)node"]
    assert len(result) > 1024
    assert validate_filter(result) == result
    assert filter_match(result, names[-1])
    assert not filter_match(result, "another-node")


def test_fixed_width_lookbehind_has_no_arbitrary_repeat_limit():
    names = ["aJP", "bJP", "JP"]
    for source, expected in [("(?<=a)JP", [True, False, False]),
                             ("(?<!a)JP", [False, True, True])]:
        normalized = normalize_filters([source], names)[source]
        assert normalized != source
        assert [filter_match(normalized, name) for name in names] == expected
    source = "(?<=a{129})JP"
    assert normalize_filters([source], names)[source] == "(?!)"
    with pytest.raises(ProxyError, match="语法"):
        normalize_filters(["(?<=a+)JP"], names)


@pytest.mark.parametrize("pattern,expected", [
    ("(a+)+$", [False, True, False, False]),
    ("(a|aa)+$", [False, True, False, False]),
    ("(a{128}){128}", [False, False, False, False]),
    ("(a)?(?(1)b|c)", [False, False, True, True]),
    ("^(?:ab){2}$", [False, False, False, False]),
    ("(" * 20 + "aa" + ")" * 20, [False, True, False, False]),
    ("(?=a)" * 20 + "a+$", [False, True, False, False]),
])
def test_valid_composite_filters_are_evaluated_instead_of_rejected_by_shape(pattern, expected):
    names = ["x", "aa", "ab", "c"]
    normalized = normalize_filters([pattern], names)[pattern]
    assert normalized != pattern
    assert [filter_match(normalized, name) for name in names] == expected


def test_tempered_token_filters_used_by_subscriptions_preserve_memberships():
    source = "(?i)^(?:(?!流量|过期|官网).)*(?:HK|香港)$"
    names = ["test-HK", "test香港", "剩余流量HK", "过期香港", "JP", "hk"]
    normalized = normalize_filters([source], names)[source]
    assert [filter_match(normalized, name) for name in names] == [
        True, True, False, False, False, True,
    ]


def test_long_alternations_and_many_backtick_alternatives_are_supported():
    alternatives = "|".join(f"region-{index:04d}" for index in range(300))
    source = f"^(?:{alternatives})$"
    many_parts = "`".join(f"^region-{index:04d}$" for index in range(40))
    names = ["region-0000", "region-0039", "region-0299", "unmatched"]
    result = normalize_filters([source, many_parts], names)
    assert [filter_match(result[source], name) for name in names] == [True, True, True, False]
    assert [filter_match(result[many_parts], name) for name in names] == [True, True, False, False]


def test_many_simple_backtick_parts_also_use_the_bounded_evaluator(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    calls = []

    def capture(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b'["0"]')

    monkeypatch.setattr(subprocess, "run", capture)
    source = "`".join(["^missing$"] * 40)
    assert normalize_filters([source], ["JP"])[source] == "(?!)"
    assert len(calls) == 1


@pytest.mark.parametrize("pattern", ["(a+)+$", "(a|aa)+$"])
def test_actual_backtracking_is_killed_without_exposing_expression_or_node(pattern):
    import time

    started = time.monotonic()
    with pytest.raises(ProxyError, match="超时|资源") as error:
        normalize_filters([pattern], ["a" * 100 + "!"])
    assert time.monotonic() - started < 5
    assert pattern not in str(error.value)
    assert "a" * 100 not in str(error.value)


def test_normalization_timeout_and_malformed_worker_result_are_safe(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret-pattern", 2)

    monkeypatch.setattr(subprocess, "run", expired)
    with pytest.raises(ProxyError) as error:
        normalize_filters(["(ab)?c"], ["abc"])
    assert "secret" not in str(error.value)
    assert "超时" in str(error.value)
    for output in [b"not-json", b'["1", "1"]', b'["101"]', b'["x"]']:
        monkeypatch.setattr(subprocess, "run", lambda *a, output=output, **k: SimpleNamespace(
            returncode=0, stdout=output))
        with pytest.raises(ProxyError):
            normalize_filters(["(ab)?c"], ["abc"])


@pytest.mark.parametrize("patterns,names", [
    (["a"] * 513, ["a"]), (["a"], ["a"] * 2305), (["a" * 16385], ["a"]),
    (["日" * 6000], ["a"]), (["a"], ["a" * 129]), ([None], ["a"]),
    (["a"], [None]), (["a"], ["bad\nname"]), (["a\n"], ["a"]),
    (["(ab)?"], ["\ud800"]), (["\ud800"], ["a"]),
])
def test_normalization_checks_all_batch_boundaries(patterns, names):
    with pytest.raises(ProxyError):
        normalize_filters(patterns, names)


def test_noncanonical_large_alternation_cannot_bypass_strict_validation():
    for malicious in ["^(?:" + "a" * 1025 + ")$", "^(?:a+|" + "b" * 1025 + ")$"]:
        with pytest.raises(ProxyError):
            validate_filter(malicious)


def test_worker_errors_distinguish_syntax_resources_and_runtime(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    for code, message in [(3, "语法"), (4, "资源"), (-9, "资源"), (2, "处理失败")]:
        monkeypatch.setattr(subprocess, "run", lambda *a, code=code, **k: SimpleNamespace(
            returncode=code, stdout=b""))
        with pytest.raises(ProxyError, match=message):
            normalize_filters(["(ab)?c"], ["abc"])


def test_worker_unavailable_has_an_actionable_message(monkeypatch):
    import subprocess

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("private-path")

    monkeypatch.setattr(subprocess, "run", unavailable)
    with pytest.raises(ProxyError, match="处理失败") as error:
        normalize_filters(["(ab)?c"], ["abc"])
    assert "private-path" not in str(error.value)


def test_frozen_decky_runtime_uses_system_python_instead_of_loader(monkeypatch):
    import subprocess
    import sys
    from types import SimpleNamespace

    calls = []

    def capture(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b'["1"]')

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/home/deck/homebrew/services/PluginLoader")
    monkeypatch.setattr(subprocess, "run", capture)
    normalize_filters(["(ab)?c"], ["abc"])
    assert calls[0][0] == "/usr/bin/python3"
    assert "PluginLoader" not in calls[0]


def test_normalized_output_growth_is_bounded(monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    names = [f"node-{index}-" + "a" * 100 for index in range(2304)]
    patterns = [f"(?=(?!missing{index}).*)node" for index in range(32)]
    output = json.dumps(["1" * len(names)] * len(patterns)).encode()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=output))
    with pytest.raises(ProxyError):
        normalize_filters(patterns, names)


def test_duplicate_fields_are_charged_for_each_serialized_occurrence():
    names = [f"node-{index}-" + "a" * 100 for index in range(2304)]
    for pattern in ["node", "(?=(?!missing).*)node"]:
        with pytest.raises(ProxyError):
            normalize_filters([pattern] * 32, names)
