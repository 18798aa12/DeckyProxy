"""Bounded YAML decoding, including ordinary anchors and merge overrides."""
import math

import yaml
from yaml.tokens import AliasToken

from .errors import ProxyError

MAX_BYTES = 4 * 1024 * 1024
MAX_TREE_ITEMS = 120_000


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        # Check explicit duplicates before merge flattening. Explicit keys may
        # override merged defaults, which is normal YAML subscription syntax.
        explicit = [key for key, _ in node.value if key.tag != "tag:yaml.org,2002:merge"]
        keys = [self.construct_object(key, deep=deep) for key in explicit]
        if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
            raise ProxyError("YAML 包含重复键或非字符串键")
        self.flatten_mapping(node)
        return super().construct_mapping(node, deep=deep)


def load_yaml(content: str) -> object:
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_BYTES:
        raise ProxyError("配置超过 4 MiB 限制")
    try:
        aliases = 0
        tokens = 0
        for token in yaml.scan(content):
            tokens += 1
            aliases += isinstance(token, AliasToken)
            if aliases > 1000 or tokens > MAX_TREE_ITEMS * 3:
                raise ProxyError("YAML 锚点或配置项目过多")
        loader = UniqueLoader(content)
        try:
            node = loader.get_single_node()
            # Composition shares alias nodes without expanding merge lists. Walk
            # every occurrence (not just unique identities) before construction
            # so flatten_mapping cannot allocate an exponential list first.
            _validate_composed_graph(node)
            value = loader.construct_document(node) if node is not None else None
        finally:
            loader.dispose()
        _validate_graph(value)
        return value
    except (yaml.YAMLError, RecursionError, ValueError, TypeError) as error:
        raise ProxyError("配置不是有效的 Clash YAML 或包含不支持的数据") from error


def _validate_composed_graph(node: yaml.Node | None) -> None:
    remaining = MAX_TREE_ITEMS
    active: set[int] = set()

    def visit(item: yaml.Node, depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 24:
            raise ProxyError("YAML 嵌套层级或锚点展开量过大")
        identity = id(item)
        if identity in active:
            raise ProxyError("YAML 锚点存在循环引用")
        if isinstance(item, (yaml.MappingNode, yaml.SequenceNode)):
            active.add(identity)
            if isinstance(item, yaml.MappingNode):
                for key, value in item.value:
                    visit(key, depth + 1)
                    visit(value, depth + 1)
            else:
                for child in item.value:
                    visit(child, depth + 1)
            active.remove(identity)

    if node is not None:
        visit(node)


def _validate_graph(value: object) -> None:
    remaining = MAX_TREE_ITEMS
    active: set[int] = set()

    def visit(item: object, depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 24:
            raise ProxyError("YAML 嵌套层级或锚点展开量过大")
        if isinstance(item, (dict, list)):
            identity = id(item)
            if identity in active:
                raise ProxyError("YAML 锚点存在循环引用")
            active.add(identity)
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ProxyError("YAML 键必须是字符串")
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ProxyError("YAML 包含不支持的数据类型")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ProxyError("配置包含无效数字")

    visit(value)
