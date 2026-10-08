"""What this repo says about itself, in one file: `state.json`.

Two halves, kept apart on purpose:

* **derived**: recomputed every run from facts (git head, branch, dirty tree,
  test result). Never written by hand.
* **stated**: judgement (where we are, what is next, what is blocked), copied
  unchanged from `STATED.json`. It carries the commit it was written at, so a
  reader can tell when it has gone stale.

Run: `python state/python/state.py` (CI runs it after the tests).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _tests() -> dict:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    return {"exit_code": r.returncode, "summary": last}


def build(run_tests: bool = True) -> dict:
    head = _git("rev-parse", "--short", "HEAD")
    stated_path = ROOT / "STATED.json"
    stated = json.loads(stated_path.read_text(encoding="utf-8")) if stated_path.exists() else None
    derived = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "head": head,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "tests": _tests() if run_tests else None,
    }
    if stated and head:
        stated = {**stated, "stale": stated.get("at_commit") != head}
    return {"schema": 1, "derived": derived, "stated": stated}


if __name__ == "__main__":
    out = ROOT / "state.json"
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
