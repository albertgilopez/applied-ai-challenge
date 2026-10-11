"""STORY-004 S4-05: every grader scores its reference solution 1 and everything else 0.

Each row of the case names a task and the score expected for every variant: the unchanged workspace,
the reference solution, an antipattern that looks right and is wrong, and each reward-hacking solution
that applies to the task. The variants a task declares must be exactly the ones the case lists. KB-06's
judge calls replay from the recordings `check-graders --live` made once.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness.replay import ReplayProvider
from keysbench.check import TASKS, JudgeContext, check_cassette, check_task, variant_names
from keysbench.cli import DEFAULT_JUDGE
from keysbench.graders import load_task

ROOT = Path(__file__).resolve().parents[2]
CASE = next(
    c for c in yaml.safe_load((ROOT / "stories" / "STORY-004.cases.yaml").read_text("utf-8")) if c["id"] == "S4-05"
)
ROWS = CASE["rows"]


def test_every_task_in_the_case_exists():
    assert sorted(r["task"] for r in ROWS) == sorted(p.name for p in TASKS.glob("KB-*") if p.is_dir())


@pytest.mark.parametrize("row", ROWS, ids=[r["task"] for r in ROWS])
def test_s4_05_solution_1_everything_else_0(row, tmp_path):
    spec = load_task(TASKS / row["task"])
    assert set(variant_names(spec)) == set(row["solutions"]), "the task's variants differ from the case"

    def judge_for(variant: str) -> JudgeContext:
        return JudgeContext(
            ReplayProvider(check_cassette(row["task"], variant)), DEFAULT_JUDGE, tmp_path / f"{variant}.jsonl"
        )

    assert check_task(TASKS / row["task"], tmp_path, judge_for) == row["solutions"]
