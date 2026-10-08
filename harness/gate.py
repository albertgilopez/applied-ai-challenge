"""The gate: one decision point in front of every tool call.

- `read`    → allow
- `write`   → allow only inside the configured roots (paths resolved first, so
              `out/../secret` does not slip through)
- `outward` → escalate to a human; the harness never runs it on its own
- anything not in the catalog → deny
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness.catalog import Tool
from harness.storage import JSONObject

Verdict = Literal["allow", "deny", "escalate"]


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str


class Gate:
    def __init__(self, write_roots: Iterable[Path | str] = (), read_roots: Iterable[Path | str] = ()) -> None:
        # Writes may go only under write_roots; a read tool that takes a path may read
        # only under read_roots (or write_roots). Its output goes to the model and the
        # ledger, so "read-only" is not "harmless" if it can be pointed at `.env`.
        self.write_roots = [Path(r).resolve() for r in write_roots]
        self.read_roots = [Path(r).resolve() for r in read_roots] + self.write_roots

    @staticmethod
    def _inside(raw: str, roots: list[Path]) -> bool:
        target = Path(raw).resolve()
        return any(target == root or root in target.parents for root in roots)

    def _check_paths(self, t: Tool, args: JSONObject, roots: list[Path], kind: str) -> Decision | None:
        for name in t.path_args:
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
        if t.effect == "outward":
            return Decision("escalate", "outward effect needs a human")
        return Decision("deny", f"unknown effect {t.effect!r}")
