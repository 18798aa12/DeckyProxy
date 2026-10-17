"""Validate routing graphs and retain supported Mihomo rule semantics."""
import copy
import re

from .errors import ProxyError

BUILTINS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}
HEALTH_URL = "https://www.gstatic.com/generate_204"
GROUP_TYPES = {"select", "url-test", "fallback", "load-balance"}
MATCHERS = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX", "GEOSITE", "GEOIP",
    "IP-CIDR", "IP-CIDR6", "IP-SUFFIX", "IP-ASN", "SRC-IP-CIDR", "SRC-IP-SUFFIX",
    "SRC-IP-ASN", "SRC-GEOIP", "DST-PORT", "SRC-PORT", "IN-PORT", "IN-TYPE",
    "IN-USER", "IN-NAME", "PROCESS-PATH", "PROCESS-PATH-REGEX", "PROCESS-NAME",
    "PROCESS-NAME-REGEX", "UID", "DSCP", "NETWORK", "RULE-SET",
}


def valid_name(value: object, kind: str = "名称") -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 128
            or re.search(r"[\x00-\x1f\x7f,]", value)):
        raise ProxyError(f"{kind}为空、过长或包含控制字符/逗号")
    return value


def normalize_groups(value: object, nodes: list[dict], providers: dict) -> list[dict]:
    if not isinstance(value, list) or len(value) > 256:
        raise ProxyError("策略组列表无效，最多支持 256 个策略组")
    groups = []
    node_names = {node["name"] for node in nodes}
    names: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ProxyError("策略组必须是对象")
        name = valid_name(raw.get("name"), "策略组名称")
        if name in names | node_names | BUILTINS | {"GLOBAL"}:
            raise ProxyError("策略组名称重复或与节点/内置策略同名")
        group_type = raw.get("type")
        if group_type not in GROUP_TYPES:
            raise ProxyError("仅支持 select、url-test、fallback、load-balance 策略组")
        group = {"name": name, "type": group_type}
        for key in ("proxies", "use"):
            if key in raw:
                entries = raw[key]
                if (not isinstance(entries, list) or len(entries) > 2256
                        or any(not isinstance(entry, str) for entry in entries)):
                    raise ProxyError("策略组引用列表无效")
                group[key] = [valid_name(entry, "策略引用") for entry in entries]
        for key in ("lazy", "disable-udp", "include-all", "include-all-proxies",
                    "include-all-providers", "hidden"):
            if key in raw:
                if type(raw[key]) is not bool:
                    raise ProxyError("策略组开关必须是布尔值")
                group[key] = raw[key]
        for key in ("interval", "tolerance", "timeout", "max-failed-times"):
            if key in raw:
                if type(raw[key]) is not int or not 0 <= raw[key] <= 86400:
                    raise ProxyError("策略组时间或阈值无效")
                group[key] = raw[key]
        for key in ("filter", "exclude-filter", "exclude-type", "expected-status"):
            if key in raw:
                if not isinstance(raw[key], str) or len(raw[key]) > 1024:
                    raise ProxyError("策略组筛选条件无效")
                group[key] = raw[key]
        if "strategy" in raw:
            if raw["strategy"] not in ("consistent-hashing", "round-robin", "sticky-sessions"):
                raise ProxyError("负载均衡策略无效")
            group["strategy"] = raw["strategy"]
        if group_type != "select":
            # Health checks use an owned endpoint, never a URL fetched as root
            # from an untrusted subscription.
            group["url"] = HEALTH_URL
            group.setdefault("interval", 600)
        groups.append(group)
        names.add(name)
    for group in groups:
        if any(item not in names | node_names | BUILTINS for item in group.get("proxies", [])):
            raise ProxyError("策略组引用了不存在的节点或策略")
        if any(item not in providers for item in group.get("use", [])):
            raise ProxyError("策略组引用了不存在的节点 provider")
        if not (group.get("proxies") or group.get("use") or any(
                group.get(key) for key in ("include-all", "include-all-proxies",
                                          "include-all-providers"))):
            raise ProxyError("策略组没有可用节点或 provider")
    adjacency = {group["name"]: [target for target in group.get("proxies", [])
                                 if target in names] for group in groups}
    _reject_cycles(adjacency)
    return copy.deepcopy(groups)


def _reject_cycles(adjacency: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ProxyError("策略组存在循环引用")
        if name in visited:
            return
        visiting.add(name)
        for target in adjacency[name]:
            visit(target)
        visiting.remove(name)
        visited.add(name)

    for name in adjacency:
        visit(name)


def _split_rule(value: str) -> list[str]:
    depth = 0
    start = 0
    fields = []
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            fields.append(value[start:index].strip())
            start = index + 1
        if depth < 0 or depth > 16:
            raise ProxyError("逻辑规则括号或嵌套层级无效")
    if depth:
        raise ProxyError("逻辑规则括号不匹配")
    return [*fields, value[start:].strip()]


def _condition(fields: list[str], providers: set[str], depth: int = 0) -> None:
    if not fields or depth > 16:
        raise ProxyError("规则为空或嵌套过深")
    rule_type = fields[0]
    if rule_type in ("IP-ASN", "SRC-IP-ASN"):
        raise ProxyError("暂不支持 ASN 规则：离线数据库未包含 ASN，请改用 GEOIP/IP-CIDR")
    if rule_type in ("AND", "OR", "NOT"):
        if len(fields) != 2 or not (fields[1].startswith("(") and fields[1].endswith(")")):
            raise ProxyError("逻辑规则格式无效")
        inner = _split_rule(fields[1][1:-1])
        if rule_type == "NOT" and len(inner) != 1:
            raise ProxyError("NOT 规则只能包含一个条件")
        for child in inner:
            if not (child.startswith("(") and child.endswith(")")):
                raise ProxyError("逻辑规则条件必须包含括号")
            _condition(_split_rule(child[1:-1]), providers, depth + 1)
        return
    if rule_type not in MATCHERS or len(fields) != 2 or not fields[1]:
        raise ProxyError("包含不支持或无效的规则类型")
    if rule_type == "RULE-SET" and fields[1] not in providers:
        raise ProxyError("规则引用了不存在的远程规则集")
    if rule_type in ("GEOIP", "SRC-GEOIP", "GEOSITE") and not re.fullmatch(
            r"!?[A-Za-z0-9_-]+(?:@!?[A-Za-z0-9_-]+)?", fields[1]):
        raise ProxyError("地理规则不能引用外部本地文件")


def validate_rules(value: object, targets: set[str], providers: set[str],
                   *, classical: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > 50_000:
        raise ProxyError("规则列表无效，最多支持 50000 条规则")
    result = []
    for rule in value:
        if (not isinstance(rule, str) or not rule.strip() or len(rule) > 4096
                or re.search(r"[\x00-\x1f\x7f]", rule)):
            raise ProxyError("规则为空、过长或包含控制字符")
        fields = _split_rule(rule)
        if fields[-1] == "no-resolve":
            fields = fields[:-1]
        if not classical:
            if len(fields) < 2 or fields[-1] not in targets | BUILTINS:
                raise ProxyError("规则引用了不存在的节点或策略组")
            target = fields[-1]
            fields = fields[:-1]
            if fields == ["MATCH"]:
                result.append(rule)
                continue
            valid_name(target, "规则目标")
        _condition(fields, providers)
        result.append(rule)
    return result
