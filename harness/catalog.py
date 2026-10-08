"""The catalog: the only actions the agent can take.

A tool that is not registered here does not exist for the agent, whatever the
model asks for. Every tool declares its effect, and the gate decides on that
declaration, never on the tool's name.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Literal, get_args

Effect = Literal["read", "write", "outward"]

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    effect: Effect
    fn: Callable[..., str]
    input_schema: dict
    path_args: tuple[str, ...] = ()

    def schema(self) -> dict:
        """The tool definition the model sees."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _schema_from_signature(fn: Callable) -> dict:
    hints = inspect.get_annotations(fn, eval_str=True)
    properties, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        properties[name] = {"type": _JSON_TYPES.get(hints.get(name, str), "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


class Catalog:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> Tool:
        if t.name in self._tools:
            raise ValueError(f"tool {t.name!r} is already registered")
        if t.effect not in get_args(Effect):
            raise ValueError(f"tool {t.name!r} declares an unknown effect {t.effect!r}")
        self._tools[t.name] = t
        return t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]


def tool(catalog: Catalog, *, effect: Effect, description: str | None = None,
         input_schema: dict | None = None, path_args: tuple[str, ...] = ()) -> Callable:
    """Register a function as a tool. `path_args` names the arguments the gate
    must confine to the allowed roots (read roots for `read`, write roots for `write`)."""

    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        catalog.register(Tool(
            name=fn.__name__,
            description=description or (fn.__doc__ or "").strip(),
            effect=effect,
            fn=fn,
            input_schema=input_schema or _schema_from_signature(fn),
            path_args=tuple(path_args),
        ))
        return fn

    return wrap
