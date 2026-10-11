"""STORY-004 S4-05: every grader scores its reference solution 1 and everything else 0.

Each row of the case names a task and the score expected for every variant: the unchanged workspace,
the reference solution, an antipattern that looks right and is wrong, and each reward-hacking solution
that applies to the task. The variants a task declares must be exactly the ones the case lists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from keysbench.check import TASKS, check_task, variant_names
from keysbench.graders import load_task

ROOT = Path(__file__).resolve().parents[2]
CASE = next(
    c for c in yaml.safe_load((ROOT / "stories" / "STORY-004.cases.yaml").read_text("utf-8")) if c["id"] == "S4-05"
)
ROWS = [r for r in CASE["rows"] if (TASKS / r["task"]).is_dir()]


@pytest.mark.parametrize("row", ROWS, ids=[r["task"] for r in ROWS])
def test_s4_05_solution_1_everything_else_0(row, tmp_path):
    spec = load_task(TASKS / row["task"])
    assert set(variant_names(spec)) == set(row["solutions"]), "the task's variants differ from the case"
    assert check_task(TASKS / row["task"], tmp_path) == row["solutions"]
