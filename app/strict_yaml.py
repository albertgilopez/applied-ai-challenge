"""A YAML loader for manifests that refuses what a manifest never needs (STORY-B01 R1).

`yaml.safe_load` keeps the last of two equal keys (`requires_human_approval: false` then `true` reads as
`true`), expands aliases without limit (334 bytes became 10^8 strings), applies merge keys, and turns
`on` into the key `True`, `1.10` into `1.1` and `2026-10-10` into a date. Each of those lets two readers
see two different manifests. This loader refuses them all and keeps the plain subset: strings, integers,
booleans, null, lists and mappings with string keys.

It subclasses the pure-Python `SafeLoader` on purpose: the C loader composes nodes in C, so the alias
guard in `compose_node` would never run.

Two kinds of failure, kept apart because they mean different things:
- `RefusedConstruct`: the document parsed, but uses a construct this format forbids. The manifest is
  unsafe: a rejection with an R1 finding (exit 1).
- `Unreadable`: missing file, over the size cap, not UTF-8, or not YAML at all (exit 2).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode

_Y = "tag:yaml.org,2002:"
ALLOWED_TAGS = frozenset(_Y + t for t in ("str", "int", "bool", "null", "seq", "map"))


class RefusedConstruct(ConstructorError):
    pass


class Unreadable(ValueError):
    pass


class StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent: Node | None, index: Any) -> Node | None:
        if self.check_event(AliasEvent):
            event = self.peek_event()  # type: ignore[no-untyped-call]
            raise RefusedConstruct(None, None, f"alias *{event.anchor} is not allowed", event.start_mark)
        return super().compose_node(parent, index)

    def construct_object(self, node: Node, deep: bool = False) -> Any:
        if node.tag not in ALLOWED_TAGS:  # explicit (!!binary, !custom) or implicit (float, timestamp, merge)
            raise RefusedConstruct(None, None, f"type {node.tag} is not allowed", node.start_mark)
        return super().construct_object(node, deep=deep)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        # Runs before the base class's flatten_mapping would apply a merge key: `<<` is tagged `merge`,
        # not `str`, so the string-key check below refuses it too. (A separate merge guard was tried
        # and a canary showed it guarded nothing this check does not.)
        seen: set[str] = set()
        for key_node, _ in node.value:
            if not (isinstance(key_node, ScalarNode) and key_node.tag == _Y + "str"):
                raise RefusedConstruct(
                    None, None, f"every key must be a string (got {key_node.tag})", key_node.start_mark
                )
            key = str(key_node.value)
            if key in seen:
                raise RefusedConstruct(None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def strict_load(text: str) -> Any:
    """Parse YAML text; RefusedConstruct for a forbidden construct, yaml.YAMLError for a syntax error."""
    return yaml.load(text, Loader=StrictLoader)  # noqa: S506 - StrictLoader is a SafeLoader subclass


def read_yaml_file(path: Path | str, limit: int) -> tuple[Any, str]:
    """(data, sha256 of the bytes read). Raises Unreadable or RefusedConstruct."""
    path = Path(path)
    try:
        raw = path.read_bytes() if path.stat().st_size <= limit else None
    except OSError as exc:
        raise Unreadable(f"{path.name}: {exc.strerror or 'cannot be read'}") from exc
    if raw is None:
        raise Unreadable(f"{path.name} is above the {limit}-byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Unreadable(f"{path.name} is not UTF-8") from exc
    try:
        data = strict_load(text)
    except RefusedConstruct:
        raise
    except (yaml.YAMLError, RecursionError) as exc:
        raise Unreadable(f"{path.name} is not valid YAML") from exc
    return data, hashlib.sha256(raw).hexdigest()
