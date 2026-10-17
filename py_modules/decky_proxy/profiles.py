"""Import full routing profiles while keeping privileged settings plugin-owned."""
import copy
from collections.abc import Callable

from .errors import ProxyError
from .profile_providers import proxy_providers, rule_providers, validate_provider_files
from .profile_rules import BUILTINS, normalize_groups, valid_name, validate_rules
from .profile_yaml import load_yaml

Download = Callable[[str], bytes]
LAN_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT", "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve", "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve", "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve", "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
]


def prepare_profile(content: str, download: Download) -> dict:
    from .configuration import validate_nodes

    value = load_yaml(content)
    if not isinstance(value, dict):
        raise ProxyError("订阅必须是 Clash/Mihomo YAML 对象")
    if value.get("script"):
        raise ProxyError("暂不支持脚本规则，请使用普通 rules 或 rule-providers")
    if value.get("sub-rules"):
        raise ProxyError("暂不支持 sub-rules，请将规则展开为普通 rules 或 rule-providers")
    inline = validate_nodes(value.get("proxies", []))
    providers, external_nodes, proxy_files = proxy_providers(
        value.get("proxy-providers", {}), download)
    nodes = validate_nodes([*inline, *external_nodes])
    if not nodes:
        raise ProxyError("订阅中没有节点，请使用 Clash/Mihomo YAML 订阅")
    groups = normalize_groups(value.get("proxy-groups", []), nodes, providers)
    rulesets, rule_files = rule_providers(value.get("rule-providers", {}), download)
    targets = {node["name"] for node in nodes} | {group["name"] for group in groups}
    if not groups:
        targets |= {"节点选择", "自动选择"}
    rules = validate_rules(value.get("rules", []), targets, set(rulesets))
    profile = {"schema_version": 2, "nodes": nodes, "inline_nodes": inline,
               "proxy_providers": providers, "groups": groups, "rules": rules,
               "rule_providers": rulesets, "provider_files": {**proxy_files, **rule_files},
               "source_rules": bool(rules), "custom_rule_sources": []}
    validate_provider_files(profile["provider_files"])
    return profile


def runtime_profile(profile: dict) -> dict:
    """Revalidate persisted data; no root settings or supplied paths pass through."""
    from .configuration import validate_nodes

    nodes = validate_nodes(profile.get("nodes", []))
    if not nodes:
        raise ProxyError("请先导入有节点的配置")
    if profile.get("schema_version") != 2:
        return {"nodes": nodes, "inline_nodes": nodes, "groups": [], "rules": [],
                "proxy_providers": {}, "rule_providers": {}, "provider_files": {},
                "source_rules": False, "custom_rule_sources": []}
    inline = validate_nodes(profile.get("inline_nodes"))
    node_names = {node["name"] for node in nodes}
    if any(node["name"] not in node_names for node in inline):
        raise ProxyError("配置中的内联节点不在节点列表中")
    files = validate_provider_files(profile.get("provider_files", {}))
    providers = _stored_providers(profile.get("proxy_providers", {}), files, is_rule=False)
    rulesets = _stored_providers(profile.get("rule_providers", {}), files, is_rule=True)
    groups = normalize_groups(profile.get("groups", []), nodes, providers)
    targets = node_names | {group["name"] for group in groups}
    if not groups:
        targets |= {"节点选择", "自动选择"}
    rules = validate_rules(profile.get("rules", []), targets, set(rulesets))
    return {"nodes": nodes, "inline_nodes": inline, "groups": groups, "rules": rules,
            "proxy_providers": providers, "rule_providers": rulesets,
            "provider_files": copy.deepcopy(profile.get("provider_files", {})),
            "source_rules": bool(profile.get("source_rules")),
            "custom_rule_sources": copy.deepcopy(profile.get("custom_rule_sources", [])),
            "schema_version": 2}


def _stored_providers(value: object, files: dict, *, is_rule: bool) -> dict:
    if not isinstance(value, dict) or len(value) > (64 if is_rule else 8):
        raise ProxyError("保存的 provider 列表无效")
    result = {}
    for name, raw in value.items():
        valid_name(name, "provider 名称")
        if not isinstance(raw, dict) or raw.get("type") != "file" or raw.get("path") not in files:
            raise ProxyError("保存的 provider 缓存路径无效")
        provider = {"type": "file", "path": raw["path"]}
        if is_rule:
            if (raw.get("behavior") not in ("domain", "ipcidr", "classical")
                    or raw.get("format") not in ("yaml", "text", "mrs")):
                raise ProxyError("保存的规则 provider 类型无效")
            provider.update(behavior=raw["behavior"], format=raw["format"])
        elif "health-check" in raw:
            health = raw["health-check"]
            from .profile_rules import HEALTH_URL
            if (not isinstance(health, dict) or type(health.get("enable")) is not bool
                    or type(health.get("interval")) is not int
                    or not 60 <= health["interval"] <= 86400):
                raise ProxyError("保存的 provider 健康检查无效")
            provider["health-check"] = {"enable": health["enable"], "url": HEALTH_URL,
                                         "interval": health["interval"]}
        result[name] = provider
    return result


def effective_rules(profile: dict) -> list[str]:
    if profile.get("rules"):
        return list(profile["rules"])
    groups = profile.get("groups", [])
    target = groups[0]["name"] if groups else "节点选择"
    return [*LAN_RULES, f"MATCH,{target}"]


def prepare_rule_provider(name: str, url: str, behavior: str, format: str, target: str,
                          profile: dict, download: Download) -> dict:
    normalized = runtime_profile(profile)
    name = valid_name(name, "规则集名称")
    custom = normalized["custom_rule_sources"]
    replacing = any(source.get("name") == name for source in custom)
    if name in normalized["rule_providers"] and not replacing:
        raise ProxyError("规则集名称已存在，请使用其他名称")
    if len(normalized["rule_providers"]) >= 64 and not replacing:
        raise ProxyError("最多支持 64 个规则集")
    targets = {node["name"] for node in normalized["nodes"]}
    targets |= {group["name"] for group in normalized["groups"]}
    if not normalized["groups"]:
        targets |= {"节点选择", "自动选择"}
    if target not in targets | BUILTINS:
        raise ProxyError("规则集目标策略不存在")
    rulesets, files = rule_providers({name: {"type": "http", "url": url,
                                          "behavior": behavior, "format": format}}, download)
    rules = effective_rules(normalized)
    old_index = next((i for i, rule in enumerate(rules)
                      if rule.startswith(f"RULE-SET,{name},")), None)
    if replacing:
        rules = [rule for rule in rules if not rule.startswith(f"RULE-SET,{name},")]
    index = old_index if replacing and old_index is not None else next(
        (i for i, rule in enumerate(rules) if rule.startswith("MATCH,")), len(rules))
    source = {"name": name, "url": url, "behavior": behavior, "format": format, "target": target}
    result = {**normalized, "schema_version": 2,
              "rules": [*rules[:index], f"RULE-SET,{name},{target}", *rules[index:]],
              "rule_providers": {**normalized["rule_providers"], **rulesets},
              "provider_files": {**normalized["provider_files"], **files},
              "custom_rule_sources": [
                  source if previous.get("name") == name else previous for previous in custom
              ] if replacing else [*custom, source]}
    used_paths = {provider["path"] for provider in {
        **result["proxy_providers"], **result["rule_providers"]}.values()}
    result["provider_files"] = {path: value for path, value in result["provider_files"].items()
                                if path in used_paths}
    validate_provider_files(result["provider_files"])
    return result
