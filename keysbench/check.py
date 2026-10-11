"""`check-graders` (STORY-004 DR-7, S4-05): a grader is trusted once it has been seen failing.

For every task: the unchanged workspace (`base`), the reference `solution/`, an `antipattern/` (looks
right, is wrong) and each reward-hacking variant the task declares are graded the same way a
contestant's workspace is. The solution must score 1 and everything else 0.
"""

from __future__ import annotations

import shutil
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness.providers import Provider
from keysbench import hacks, judge
from keysbench.graders import GradeResult, TaskSpec, grade_pytest, load_task

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
RUBRICS = HERE / "rubrics"
CHECK_CASSETTES = HERE / "cassettes" / "check-graders"
MAX_REVIEW_CHARS = 20_000


@dataclass(frozen=True)
class JudgeContext:
    provider: Provider
    model: str
    ledger_path: Path


JudgeFor = Callable[[str], JudgeContext]  # variant or attempt name -> where the judge's call goes


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


def grade_judge(spec: TaskSpec, workspace: Path, ctx: JudgeContext) -> GradeResult:
    """KB-06: the review is read as data from the one editable file; the judge decides, code checks."""
    assert spec.path is not None
    rubric = tomllib.loads((RUBRICS / str(spec.raw["rubric"])).read_text("utf-8"))
    name = str(spec.raw["review_file"])
    path = workspace / name
    review = path.read_text("utf-8", errors="replace") if path.is_file() and not path.is_symlink() else ""
    env = spec.path / "environment"
    r = judge.judge_review(
        review=review[:MAX_REVIEW_CHARS],
        diff=(env / str(spec.raw["diff_file"])).read_text("utf-8"),
        planted_line=str(rubric["planted_line"]),
        marker=str(rubric["marker"]),
        judge_model=ctx.model,
        provider=ctx.provider,
        ledger_path=ctx.ledger_path,
        placeholder=(env / name).read_text("utf-8"),
    )
    passed = r["verdict"] == "pass"
    return GradeResult(passed, () if passed else (f"judge:{r['reason']}",), str(r["reason"]), judge=r)


def grade(spec: TaskSpec, workspace: Path, dest: Path, judge_ctx: JudgeContext | None = None) -> GradeResult:
    if spec.family == "pytest":
        return grade_pytest(spec, workspace, dest)
    if spec.family == "judge":
        if judge_ctx is None:
            raise ValueError(f"{spec.id}: a judge task needs a judge")
        return grade_judge(spec, workspace, judge_ctx)
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


def check_task(task_dir: Path, work: Path, judge_for: JudgeFor | None = None) -> dict[str, int]:
    spec = load_task(task_dir)
    scores: dict[str, int] = {}
    for name in variant_names(spec):
        workspace = build_variant(spec, name, work / spec.id / name / "w")
        ctx = judge_for(name) if judge_for is not None and spec.family == "judge" else None
        scores[name] = int(grade(spec, workspace, work / spec.id / name / "g", ctx).passed)
    return scores


def check_cassette(task_id: str, variant: str) -> Path:
    return CHECK_CASSETTES / task_id / f"{variant}.jsonl"


def expected_scores(spec: TaskSpec) -> dict[str, int]:
    return {name: int(name == "solution") for name in variant_names(spec)}
