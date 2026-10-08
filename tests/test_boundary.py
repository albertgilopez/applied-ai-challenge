"""The boundary is a test, not an agreement (DOCTRINE D-01).

`core/` holds the decision Legal relies on. It may import the standard library
and itself, nothing else: no model SDK, no HTTP client, no YAML parser. Every
file is parsed with `ast`, so the check sees imports inside functions too, and
the failure names the file and the import.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PURE_PACKAGES = ("core",)
STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def _modules() -> list[Path]:
    return sorted(p for pkg in PURE_PACKAGES for p in (REPO / pkg).rglob("*.py"))


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module)
    return found


def _allowed(module: str) -> bool:
    root = module.split(".")[0]
    return root in STDLIB or root in PURE_PACKAGES


def test_pure_packages_exist():
    """A boundary check over an empty tree passes for the wrong reason."""
    assert _modules(), f"no Python files under {PURE_PACKAGES}: the boundary test would check nothing"


def test_core_imports_only_stdlib_and_itself():
    offenders = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders += [f"{path.relative_to(REPO)}: import {m}" for m in sorted(_imports(tree)) if not _allowed(m)]
    assert not offenders, "core/ must stay pure (DOCTRINE D-01):\n  " + "\n  ".join(offenders)
