"""Copied by the grader into every grading directory; hidden tests import it. The contestant never sees
or edits it.

`call` runs the contestant's code in a separate, isolated Python process and returns its result parsed
from JSON. Nothing the contestant's code does in that process (patching the test runner, returning an
object that claims to equal anything, exiting early) reaches the test's own process: only plain JSON
comes back, and `strict_equal` compares it by type as well as value.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MARKER = "KBRESULT "
HERE = Path(__file__).resolve().parent


class CallFailed(AssertionError):
    pass


def call(expression: str, *modules: str, setup: str = "", timeout_s: float = 30.0) -> Any:
    """Evaluate `expression` after importing `modules` from the grading directory, in a fresh `python -I`.

    `setup` is run first (statements, e.g. a try/except that turns an expected exception into a value).
    `python -I` ignores PYTHON* variables and the user site, and does not put the working directory on
    the path; the grading directory is added explicitly, and only it."""
    imports = "".join(f"import {m}\n" for m in modules)
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(HERE)!r})\n"
        f"{imports}"
        f"{setup}\n"
        f"_r = {expression}\n"
        f"sys.stdout.write({MARKER!r} + json.dumps(_r, allow_nan=False) + chr(10))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        cwd=HERE,
        env=dict(os.environ),  # already the grader's credential-free environment
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(MARKER)]
    if proc.returncode != 0 or len(lines) != 1:
        raise CallFailed(f"exit {proc.returncode}; stderr: {proc.stderr[-500:]}")
    return json.loads(lines[0][len(MARKER) :])


def strict_equal(actual: Any, expected: Any, tol: float = 0.0) -> bool:
    """Equal by type and value: `True` is not `1`, `1` is not `1.0`. Floats within `tol` (absolute)."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, float):
        return bool(abs(actual - expected) <= tol)
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(strict_equal(actual[k], expected[k], tol) for k in expected)
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return False
        return all(strict_equal(a, e, tol) for a, e in zip(actual, expected, strict=True))
    return bool(actual == expected)
