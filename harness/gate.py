"""The gate: one decision point in front of every tool call.

- `read`    → allow
- `write`   → allow only inside the configured roots (paths resolved first, so
              `out/../secret` does not slip through)
- `outward`, `physical` → escalate to a human; the harness never runs them on its own
- anything not in the catalog → deny
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from harness.catalog import Tool
from harness.storage import JSONObject

Verdict = Literal["allow", "deny", "escalate"]


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str


class Gate:
    def __init__(
        self,
        write_roots: Iterable[Path | str] = (),
        read_roots: Iterable[Path | str] = (),
        base: Path | str | None = None,
    ) -> None:
        # Writes may go only under write_roots; a read tool that takes a path may read
        # only under read_roots (or write_roots). Its output goes to the model and the
        # ledger, so "read-only" is not "harmless" if it can be pointed at `.env`.
        #
        # With a `base` (a benchmark workspace), roots and tool paths are relative to it, and a
        # tool path must be relative: absolute paths and `..` are refused outright, and a
        # backslash is read as `/`. The prompt never names the temporary directory, so a
        # recording made on one machine replays on another (STORY-004 DR-12). Without a base,
        # paths resolve against the process working directory, as before.
        self.base = None if base is None else Path(base).resolve()
        self.write_roots = [self._root(r) for r in write_roots]
        self.read_roots = [self._root(r) for r in read_roots] + self.write_roots

    def _root(self, raw: Path | str) -> Path:
        path = Path(raw)
        if self.base is not None and not path.is_absolute():
            return (self.base / path).resolve()
        return path.resolve()

    def resolve(self, raw: str) -> Path | None:
        """The one path a tool argument names, or None if it is refused. Tools call this too, so the
        gate and the tool always check and use the same path."""
        if self.base is None:
            return Path(raw).resolve()
        if not raw or "\0" in raw:
            return None
        rel = PurePosixPath(raw.replace("\\", "/"))
        if rel.is_absolute() or PureWindowsPath(raw).drive or ".." in rel.parts:
            return None
        return (self.base / rel).resolve()

    def _inside(self, raw: str, roots: list[Path]) -> bool:
        target = self.resolve(raw)
        return target is not None and any(target == root or root in target.parents for root in roots)

    def _check_paths(self, t: Tool, args: JSONObject, roots: list[Path], kind: str) -> Decision | None:
        for name in t.path_args or ():
            value = args.get(name)
            if not isinstance(value, str) or not self._inside(value, roots):
                return Decision("deny", f"{name}={value!r} is outside the allowed {kind} roots")
        return None

    def decide(self, t: Tool | None, args: JSONObject) -> Decision:
        if t is None:
            return Decision("deny", "tool is not in the catalog")
        if t.effect == "read":
            return self._check_paths(t, args, self.read_roots, "read") or Decision("allow", "read-only tool")
        if t.effect == "write":
            if not t.path_args:
                return Decision("deny", "write tool declares no path arguments to check")
            return self._check_paths(t, args, self.write_roots, "write") or Decision(
                "allow", "write inside allowed roots"
            )
        if t.effect in ("outward", "physical"):
            return Decision("escalate", f"{t.effect} effect needs a human")
        return Decision("deny", f"unknown effect {t.effect!r}")
