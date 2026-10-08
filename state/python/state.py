"""What this repo says about itself, in one file: `state.json`.

Two halves, kept apart on purpose:

* **derived**: recomputed every run from facts (git head, branch, dirty tree,
  test result). Never written by hand.
* **stated**: judgement (where we are, what is next, what is blocked), copied
  unchanged from `STATED.json`. It carries the commit it was written at, so a
  reader can tell when it has gone stale.

Run: `uv run python state/python/state.py` (CI runs it after the tests).
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
    # pyproject already adds -q; a second -q would suppress the summary line.
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    summary = next((l.strip(" =") for l in reversed(r.stdout.splitlines()) if " in " in l and ("passed" in l or "failed" in l or "error" in l)), "")
    return {"exit_code": r.returncode, "summary": summary}


def _stale(at_commit: str | None) -> bool:
    """The judgement is stale once anything other than STATED.json changed after it was written."""
    if not at_commit:
        return True
    changed = _git("log", "--format=%h", f"{at_commit}..HEAD", "--", ".", ":(exclude)STATED.json")
    return changed is None or bool(changed)


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
    if stated:
        stated = {**stated, "stale": _stale(stated.get("at_commit"))}
    return {"schema": 1, "derived": derived, "stated": stated}


if __name__ == "__main__":
    out = ROOT / "state.json"
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
