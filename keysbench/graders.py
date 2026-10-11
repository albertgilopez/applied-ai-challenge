"""Graders (STORY-004 DR-6, DR-7): they run after the attempt, on a second copy, and trust nothing the
contestant wrote except the declared files.

- Only the task's `editable` files cross from the workspace into a fresh grading directory, next to the
  hidden tests and `kbcall.py`. A planted `conftest.py`, `pytest.py` or `pytest.ini` never gets there.
- pytest runs as `python -I -B -m pytest --noconftest -p no:cacheprovider`, with its ini file and its
  JUnit report outside the grading directory, plugin autoload off, a wall-clock limit, and an
  environment that holds no credential.
- A pass needs the report to list **every** expected test as passed. No report (an early `os._exit(0)`),
  a partial report, a skip, an xfail or an error are all a fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# What the grading run inherits: enough for Python to start on Windows and Linux, nothing else. No
# ANTHROPIC_*, no CREDENTIALS_*, no HOME-based configuration.
_KEEP = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL")


@dataclass(frozen=True)
class TaskSpec:
    id: str
    family: str
    editable: tuple[str, ...]
    expected_tests: tuple[str, ...]
    timeout_s: int
    raw: dict[str, Any] = field(default_factory=dict, compare=False)
    path: Path | None = field(default=None, compare=False)  # the task directory


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    failed_checks: tuple[str, ...]
    detail: str = ""
    judge: dict[str, Any] | None = None  # KB-06: the judge's frozen verdict and the digests it rests on


def load_task(task_dir: Path) -> TaskSpec:
    raw = tomllib.loads((task_dir / "task.toml").read_text("utf-8"))
    return TaskSpec(
        id=str(raw["id"]),
        family=str(raw["family"]),
        editable=tuple(str(e) for e in raw["editable"]),
        expected_tests=tuple(str(t) for t in raw.get("expected_tests", ())),
        timeout_s=int(raw.get("timeout_s", 120)),
        raw=raw,
        path=task_dir,
    )


def grading_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in _KEEP}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _copy_tree(src_root: Path, dest: Path) -> None:
    for src in sorted(src_root.rglob("*")):
        if src.is_file() and not src.is_symlink() and "__pycache__" not in src.parts:
            target = dest / src.relative_to(src_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)


def build_grading_dir(spec: TaskSpec, task_dir: Path, workspace: Path, dest: Path) -> None:
    """The task's pristine `environment/`, then the declared editable files from the workspace on top,
    then the hidden tests and `kbcall.py`. Nothing else from the workspace crosses."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if (task_dir / "environment").is_dir():
        _copy_tree(task_dir / "environment", dest)
    for rel in spec.editable:
        src = workspace / rel
        target = dest / rel
        # A symlink could point anywhere; only a regular file inside the workspace crosses. An editable
        # file the contestant deleted is deleted here too, so "remove the bug by removing the module"
        # is graded as what it is.
        if src.is_file() and not src.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
        elif target.exists():
            target.unlink()
    _copy_tree(task_dir / "tests", dest)
    shutil.copyfile(HERE / "kbcall.py", dest / "kbcall.py")


def _junit(report: Path) -> dict[str, str]:
    """test id (`file::name`) -> outcome (`passed`, `failed`, `error`, `skipped`)."""
    outcomes: dict[str, str] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        classname = case.get("classname", "")
        module = classname.split(".")[-1] if classname else ""
        test_id = f"{module}.py::{case.get('name')}"
        tags = {child.tag for child in case}
        outcomes[test_id] = next((t for t in ("failure", "error", "skipped") if t in tags), "passed")
    return outcomes


def _check_name(test_id: str) -> str:
    return test_id.split("::")[-1]


def grade_pytest(spec: TaskSpec, workspace: Path, dest: Path) -> GradeResult:
    if spec.path is None:
        raise ValueError(f"{spec.id}: load the task with load_task, which records its directory")
    build_grading_dir(spec, spec.path, workspace, dest)
    return run_pytest(spec, dest)


def run_pytest(spec: TaskSpec, dest: Path) -> GradeResult:
    """The second layer, on an already-built directory. It must hold on its own even if something
    planted got past the copy: `--noconftest` ignores a conftest, `-I` keeps a `pytest.py` in the
    directory from shadowing pytest, and the verdict comes from a report written outside the
    directory, never from the exit code."""
    with tempfile.TemporaryDirectory(prefix="kb-grade-") as outside:
        ini = Path(outside) / "pytest.ini"
        ini.write_text("[pytest]\naddopts =\n", encoding="utf-8")
        report = Path(outside) / "junit.xml"
        cmd = [
            sys.executable, "-I", "-B", "-m", "pytest",
            "--noconftest", "-p", "no:cacheprovider",
            "-c", str(ini), "--rootdir", str(dest), f"--junitxml={report}", "-q", str(dest),
        ]  # fmt: skip
        try:
            proc = subprocess.run(
                cmd,
                cwd=dest,
                env=grading_env(),
                capture_output=True,
                text=True,
                timeout=spec.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return GradeResult(False, ("timeout",), f"no result within {spec.timeout_s} s")
        if not report.is_file():
            return GradeResult(False, ("no_report",), f"exit {proc.returncode} and no test report")
        outcomes = _junit(report)
    failed = tuple(_check_name(t) for t in spec.expected_tests if outcomes.get(t) != "passed")
    return GradeResult(not failed, failed, proc.stdout[-2000:])
