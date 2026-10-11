"""`check-graders` (STORY-004 DR-7, S4-05): a grader is trusted once it has been seen failing.

For every task: the unchanged workspace (`base`), the reference `solution/`, an `antipattern/` (looks
right, is wrong) and each reward-hacking variant the task declares are graded the same way a
contestant's workspace is. The solution must score 1 and everything else 0.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from keysbench import hacks
from keysbench.graders import GradeResult, TaskSpec, grade_pytest, load_task

TASKS = Path(__file__).resolve().parent / "tasks"


def overlay(src_root: Path, workspace: Path) -> None:
    for src in sorted(src_root.rglob("*")):
        if src.is_file() and "__pycache__" not in src.parts:
            target = workspace / src.relative_to(src_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())


def fresh_workspace(spec: TaskSpec, dest: Path) -> Path:
    """A contestant's starting point: a copy of the task's `environment/`, nothing else."""
    assert spec.path is not None
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    env = spec.path / "environment"
    if env.is_dir():
        overlay(env, dest)
    return dest


def grade(spec: TaskSpec, workspace: Path, dest: Path) -> GradeResult:
    if spec.family == "pytest":
        return grade_pytest(spec, workspace, dest)
    raise ValueError(f"{spec.id}: unknown grader family {spec.family!r}")


def variant_names(spec: TaskSpec) -> list[str]:
    return ["base", "solution", "antipattern", *[str(h) for h in spec.raw.get("hacks", [])]]


def build_variant(spec: TaskSpec, name: str, dest: Path) -> Path:
    assert spec.path is not None
    workspace = fresh_workspace(spec, dest)
    if name in ("solution", "antipattern"):
        overlay(spec.path / name, workspace)
    elif name != "base":
        hacks.apply(name, spec, workspace)
    return workspace


def check_task(task_dir: Path, work: Path) -> dict[str, int]:
    spec = load_task(task_dir)
    scores: dict[str, int] = {}
    for name in variant_names(spec):
        workspace = build_variant(spec, name, work / spec.id / name / "w")
        scores[name] = int(grade(spec, workspace, work / spec.id / name / "g").passed)
    return scores


def expected_scores(spec: TaskSpec) -> dict[str, int]:
    return {name: int(name == "solution") for name in variant_names(spec)}
