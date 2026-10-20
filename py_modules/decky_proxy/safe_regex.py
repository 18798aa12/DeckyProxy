"""Materialize subscription filters into bounded, literal node memberships.

Simple expressions use a conservative fast path. All other source expressions
run in an isolated evaluator with CPU, memory and wall-clock limits. Neither the
root controller nor Mihomo receives the original backtracking expression.
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from re import _constants as constants
from re import _parser as parser

from .errors import ProxyError

_ERROR = "节点筛选表达式过于复杂或不兼容，请简化后重新导入"
_INPUT_ERROR = "节点筛选条件数据无效或超过容量限制"
_SYNTAX_ERROR = "节点筛选正则语法无效或暂不支持，请检查订阅的筛选条件"
_BUDGET_ERROR = "节点筛选执行超时或超过资源限制，当前配置未更改"
_WORKER_ERROR = "节点筛选处理失败，请更新插件后重试"
_MAX_NAMES = 2304
_MAX_SOURCE_BYTES = 16 * 1024
_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
_MAX_CANONICAL_LENGTH = 1_800_000
_MAX_NORMALIZED_BYTES = 4 * 1024 * 1024
_FLAGS = re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE
_ATOMS = {constants.LITERAL, constants.NOT_LITERAL, constants.ANY, constants.IN}
_REPEATS = {constants.MAX_REPEAT, constants.MIN_REPEAT}
_ASSERTIONS = {constants.ASSERT, constants.ASSERT_NOT}
_CLASS_ITEMS = {constants.LITERAL, constants.RANGE, constants.NEGATE, constants.CATEGORY}
_CATEGORIES = {
    constants.CATEGORY_DIGIT, constants.CATEGORY_NOT_DIGIT,
    constants.CATEGORY_SPACE, constants.CATEGORY_NOT_SPACE,
    constants.CATEGORY_WORD, constants.CATEGORY_NOT_WORD,
}
_ANCHORS = {
    constants.AT_BEGINNING, constants.AT_BEGINNING_LINE, constants.AT_BEGINNING_STRING,
    constants.AT_END, constants.AT_END_LINE, constants.AT_END_STRING,
    constants.AT_BOUNDARY, constants.AT_NON_BOUNDARY,
}


@dataclass(frozen=True)
class _Cost:
    variables: int = 0
    nodes: int = 0
    assertions: int = 0


def _reject() -> None:
    raise ProxyError(_ERROR)


def _atom(sequence: parser.SubPattern, depth: int) -> bool:
    """A repeat may contain only one consuming atom, optionally grouped."""
    if depth > 8 or len(sequence) != 1:
        return False
    operation, value = sequence[0]
    if operation in _ATOMS:
        return True
    if operation == constants.SUBPATTERN:
        return _atom(value[3], depth + 1)
    return False


def _walk(sequence: parser.SubPattern, depth: int = 0, in_assertion: bool = False) -> _Cost:
    if depth > 8:
        _reject()
    cost = _Cost()
    for operation, value in sequence:
        child = _Cost()
        if operation in {constants.LITERAL, constants.NOT_LITERAL, constants.ANY,
                         constants.FAILURE}:
            # Python 3.13 folds (?!) into FAILURE. It always fails immediately
            # and is the exact empty-membership pattern emitted by this module.
            pass
        elif operation == constants.AT:
            if value not in _ANCHORS:
                _reject()
        elif operation == constants.IN:
            for item, argument in value:
                if item not in _CLASS_ITEMS:
                    _reject()
                if item == constants.CATEGORY and argument not in _CATEGORIES:
                    _reject()
            child = _Cost(nodes=len(value))
        elif operation == constants.SUBPATTERN:
            _, added_flags, removed_flags, contents = value
            if (added_flags | removed_flags) & ~_FLAGS:
                _reject()
            child = _walk(contents, depth + 1, in_assertion)
        elif operation == constants.BRANCH:
            alternatives = tuple(_walk(branch, depth + 1, in_assertion)
                                 for branch in value[1])
            child = _Cost(
                variables=max((branch.variables for branch in alternatives), default=0),
                nodes=sum(branch.nodes for branch in alternatives),
                assertions=sum(branch.assertions for branch in alternatives),
            )
        elif operation in _REPEATS:
            lower, upper, contents = value
            if lower > 128 or (upper != constants.MAXREPEAT and upper > 128):
                _reject()
            if not _atom(contents, depth + 1):
                _reject()
            repeated = _walk(contents, depth + 1, in_assertion)
            child = _Cost(int(lower != upper) + repeated.variables,
                          repeated.nodes, repeated.assertions)
        elif operation in _ASSERTIONS:
            direction, contents = value
            # Nested lookaheads can multiply backtracking across otherwise safe
            # individual sequences. Only sibling forward assertions are allowed.
            if direction != 1:
                _reject()
            if in_assertion:
                _reject()
            assertion = _walk(contents, depth + 1, True)
            child = _Cost(nodes=assertion.nodes, assertions=assertion.assertions + 1)
        else:
            _reject()
        cost = _Cost(
            cost.variables + child.variables,
            cost.nodes + child.nodes + 1,
            cost.assertions + child.assertions,
        )
        if cost.variables > 1 or cost.nodes > 256 or cost.assertions > 4:
            _reject()
    return cost


def _parse(pattern: str) -> None:
    if (not isinstance(pattern, str) or len(pattern) > 1024
            or re.search(r"[\x00-\x1f\x7f]", pattern)):
        _reject()
    # Python's default Unicode mode must not make explicit Python-only flags
    # appear compatible with .NET. A conservative lexical check covers (?u).
    if re.search(r"\(\?[imsxauL-]*[auL]", pattern):
        _reject()
    try:
        parsed = parser.parse(pattern, 0)
        if parsed.state.flags & ~(_FLAGS | re.UNICODE):
            _reject()
        _walk(parsed)
    except (re.error, OverflowError, RecursionError, ValueError, TypeError):
        raise ProxyError(_ERROR) from None


def _escape_name(name: str) -> str:
    # Backticks delimit Mihomo's independent filters even inside a regex, so
    # represent literal backticks through the shared Python/.NET Unicode escape.
    return re.escape(name).replace("`", r"\u0060")


@lru_cache(maxsize=4)
def _canonical_names(pattern: str) -> frozenset[str] | None:
    """Recognize only our exact escaped-name serialization, never arbitrary regex."""
    if (len(pattern) > _MAX_CANONICAL_LENGTH or not pattern.startswith("^(?:")
            or not pattern.endswith(")$")):
        return None
    body = pattern[4:-2]
    branches, start, index = [], 0, 0
    while index < len(body):
        if body[index] == "\\":
            index += 2
            continue
        if body[index] == "|":
            branches.append(body[start:index])
            start = index + 1
            if len(branches) >= _MAX_NAMES:
                return None
        index += 1
    branches.append(body[start:])
    names = []
    for branch in branches:
        decoded, index = [], 0
        while index < len(branch):
            if branch.startswith(r"\u0060", index):
                decoded.append("`")
                index += 6
            elif branch[index] == "\\" and index + 1 < len(branch):
                decoded.append(branch[index + 1])
                index += 2
            else:
                decoded.append(branch[index])
                index += 1
        name = "".join(decoded)
        if (not name or len(name) > 128 or re.search(r"[\x00-\x1f\x7f]", name)
                or _escape_name(name) != branch):
            return None
        names.append(name)
    return frozenset(names)


@lru_cache(maxsize=128)
def _checked_pattern(pattern: str) -> re.Pattern[str]:
    _parse(pattern)
    return re.compile(pattern)


def validate_filter(pattern: str) -> str:
    """Return a core-safe original or strictly canonical exact-name pattern."""
    if not isinstance(pattern, str):
        _reject()
    if _canonical_names(pattern) is None:
        _checked_pattern(pattern)
    return pattern


def filter_match(pattern: str, text: str) -> bool:
    """Validate before matching a node name, whose import limit is 128 chars."""
    validate_filter(pattern)
    if not isinstance(text, str) or len(text) > 128:
        _reject()
    names = _canonical_names(pattern)
    if names is not None:
        return text in names
    return _checked_pattern(pattern).search(text) is not None


def _retain(values: dict[str, str], key: str, value: str,
            used_bytes: int) -> tuple[dict[str, str], int]:
    try:
        next_bytes = (used_bytes - len(values.get(key, "").encode("utf-8"))
                      + len(value.encode("utf-8")))
    except UnicodeError:
        raise ProxyError(_INPUT_ERROR) from None
    if next_bytes > _MAX_NORMALIZED_BYTES:
        raise ProxyError(_INPUT_ERROR)
    return {**values, key: value}, next_bytes


def _exact_names(names: list[str]) -> str:
    selected = tuple(dict.fromkeys(names))
    return "^(?:" + "|".join(_escape_name(name) for name in selected) + ")$" if selected else "(?!)"


def _bounded_result(patterns: list[str], normalized: dict[str, str]) -> dict[str, str]:
    # The mapping deduplicates expressions, but a profile serializes each group
    # and provider field separately. Charge the budget for every occurrence.
    total_bytes = 0
    for pattern in patterns:
        total_bytes += len(normalized[pattern].encode("utf-8"))
        if total_bytes > _MAX_NORMALIZED_BYTES:
            raise ProxyError(_INPUT_ERROR)
    return normalized


def normalize_filters(patterns: list[str], names: list[str]) -> dict[str, str]:
    """Replace nonempty source filters with exact memberships for both engines.

    Strict filters match in process; other expressions share one bounded child.
    The child receives patterns and names through stdin, never argv/files. Empty
    strings retain Mihomo's special meaning of an absent inclusion/exclusion.
    """
    if (not isinstance(patterns, list) or len(patterns) > 512
            or not isinstance(names, list) or len(names) > _MAX_NAMES):
        raise ProxyError(_INPUT_ERROR)
    for name in names:
        if (not isinstance(name, str) or not name or len(name) > 128
                or re.search(r"[\x00-\x1f\x7f]", name)):
            raise ProxyError(_INPUT_ERROR)
        try:
            name.encode("utf-8")
        except UnicodeError:
            raise ProxyError(_INPUT_ERROR) from None
    normalized, pending, used_bytes = {}, [], 0
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise ProxyError(_INPUT_ERROR)
        if _canonical_names(pattern) is not None:
            normalized, used_bytes = _retain(normalized, pattern, pattern, used_bytes)
            continue
        if not pattern:
            normalized, used_bytes = _retain(normalized, pattern, pattern, used_bytes)
            continue
        try:
            if (len(pattern.encode("utf-8")) > _MAX_SOURCE_BYTES
                    or re.search(r"[\x00-\x1f\x7f]", pattern)):
                raise ProxyError(_INPUT_ERROR)
        except UnicodeError:
            raise ProxyError(_INPUT_ERROR) from None
        expressions = pattern.split("`")
        try:
            # Many individually simple alternatives must share the same CPU
            # deadline as composite expressions, rather than block the backend.
            if len(expressions) > 16:
                raise ProxyError(_ERROR)
            for expression in expressions:
                validate_filter(expression)
        except ProxyError:
            if pattern not in pending:
                pending.append(pattern)
        else:
            selected = [name for name in names if any(filter_match(expression, name)
                                                      for expression in expressions)]
            normalized, used_bytes = _retain(
                normalized, pattern, _exact_names(selected), used_bytes,
            )
    if not pending:
        return _bounded_result(patterns, normalized)
    payload = json.dumps({"patterns": pending, "names": names}, ensure_ascii=False).encode()
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise ProxyError(_INPUT_ERROR)
    try:
        executable = "/usr/bin/python3" if sys.platform == "linux" or getattr(
            sys, "frozen", False) else sys.executable
        result = subprocess.run(
            [executable, "-I", str(Path(__file__).with_name("regex_worker.py"))],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2,
            check=False, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        if result.returncode == 3:
            raise ProxyError(_SYNTAX_ERROR)
        if result.returncode < 0 or result.returncode == 4:
            raise ProxyError(_BUDGET_ERROR)
        if result.returncode or len(result.stdout) > len(pending) * (len(names) + 4) + 2:
            raise ProxyError(_WORKER_ERROR)
        bitsets = json.loads(result.stdout)
        if not isinstance(bitsets, list) or len(bitsets) != len(pending):
            raise ProxyError(_WORKER_ERROR)
        for pattern, bits in zip(pending, bitsets, strict=True):
            if (not isinstance(bits, str) or len(bits) != len(names)
                    or set(bits) - {"0", "1"}):
                raise ProxyError(_WORKER_ERROR)
            selected = [name for name, bit in zip(names, bits, strict=True) if bit == "1"]
            value = _exact_names(selected)
            normalized, used_bytes = _retain(normalized, pattern, value, used_bytes)
    except subprocess.TimeoutExpired:
        raise ProxyError(_BUDGET_ERROR) from None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        raise ProxyError(_WORKER_ERROR) from None
    return _bounded_result(patterns, normalized)
