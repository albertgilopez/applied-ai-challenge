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
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _tests() -> dict:
    # Counts come from the JUnit XML report, not from pytest's human-readable
    # output (whose summary line moves with -q flags and pytest versions). The
    # exit code stays the verdict.
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
                           cwd=ROOT, capture_output=True, text=True)
        counts = {}
        if report.exists():
            suite = ET.parse(report).getroot()
            suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
            counts = {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
    return {"exit_code": r.returncode, **counts}


def _stale(stated: dict) -> bool:
    """The judgement is stale once anything other than STATED.json changed after it was written.

    "When it was written" comes from git (the last commit that touched STATED.json),
    not from the hand-written `at_commit`, which is only cross-checked.
    """
    anchor = _git("log", "-1", "--format=%h", "--", "STATED.json")
    if not anchor:
        return True
    changed = _git("log", "--format=%h", f"{anchor}..HEAD", "--", ".", ":(exclude)STATED.json")
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
        stated = {**stated, "stale": _stale(stated)}
        anchor = _git("log", "-1", "--format=%h", "--", "STATED.json")
        # `git merge-base --is-ancestor` exits 1 when it is not an ancestor; _git returns None then.
        if anchor and stated.get("at_commit") and _git("merge-base", "--is-ancestor", stated["at_commit"], anchor) is None:
            stated["at_commit_warning"] = f"at_commit {stated['at_commit']} is not an ancestor of {anchor}"
    return {"schema": 1, "derived": derived, "stated": stated}


if __name__ == "__main__":
    out = ROOT / "state.json"
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)}")
