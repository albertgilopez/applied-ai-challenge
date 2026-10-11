"""Build a history task from a fix commit (STORY-004 § Tasks).

Pointed at an organisation's repositories, this is the monthly feed: a fix commit becomes a task whose
workspace is the parent tree without history, whose reference solution is the fixed files, and whose
hidden tests are the tests the fix added (checked to fail on the parent by `check-graders`).

    python -m keysbench.extract --repo . --commit 341fb07 --include core --editable core/license_expr.py \
        --task keysbench/tasks/KB-01

It writes `environment/` and `solution/` only; `task.toml`, `instruction.md`, `tests/`, `antipattern/`
and `hacks/` are written by a person, and an existing `environment/` or `solution/` is replaced whole.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def files_at(repo: Path, commit: str, include: list[str]) -> list[str]:
    out = _git(repo, "ls-tree", "-r", "--name-only", commit, "--", *include).decode("utf-8")
    return [p for p in out.splitlines() if p and "__pycache__" not in p]


def show(repo: Path, commit: str, path: str) -> bytes:
    # `git show` returns the blob as committed (LF here), never the working-tree copy.
    return _git(repo, "show", f"{commit}:{path}")


def extract(repo: Path, commit: str, include: list[str], editable: list[str], task: Path) -> dict[str, int]:
    parent = f"{commit}^"
    environment, solution = task / "environment", task / "solution"
    for d in (environment, solution):
        if d.exists():
            shutil.rmtree(d)
    paths = files_at(repo, parent, include)
    for path in paths:
        target = environment / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(show(repo, parent, path))
    for path in editable:
        target = solution / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(show(repo, commit, path))
    return {"environment_files": len(paths), "solution_files": len(editable)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="keysbench.extract")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--commit", required=True)
    ap.add_argument("--include", action="append", required=True)
    ap.add_argument("--editable", action="append", required=True)
    ap.add_argument("--task", type=Path, required=True)
    a = ap.parse_args(argv)
    print(extract(a.repo, a.commit, a.include, a.editable, a.task))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
