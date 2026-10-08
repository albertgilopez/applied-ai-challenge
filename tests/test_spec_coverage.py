"""A story is prose unless something checks that each of its claims has a case.

Every `stories/STORY-NNN.md` needs a `STORY-NNN.cases.yaml` next to it, the
cases file must not be empty, and every checkbox under `## Acceptance Criteria`
must cite a `(case: ID)` that exists in it. A checkbox without a case is a
promise no test runs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

STORIES = Path(__file__).resolve().parents[1] / "stories"
CHECKBOX = re.compile(r"^- \[[ x]\]\s")
CASE_REF = re.compile(r"\(case:\s*([A-Za-z0-9_-]+)\)")


def _stories() -> list[Path]:
    return sorted(STORIES.glob("STORY-*.md"))


def _cases(story: Path) -> list[dict]:
    path = story.with_name(story.stem + ".cases.yaml")
    assert path.exists(), f"{story.name} has no {path.name}"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def test_there_are_stories():
    assert _stories(), "no stories under stories/: coverage would check nothing"


@pytest.mark.parametrize("story", _stories(), ids=lambda p: p.stem)
def test_cases_file_is_not_empty(story: Path):
    assert _cases(story), f"{story.stem}.cases.yaml has no rows"


@pytest.mark.parametrize("story", _stories(), ids=lambda p: p.stem)
def test_every_checkbox_cites_an_existing_case(story: Path):
    known = {c["id"] for c in _cases(story) if isinstance(c, dict) and "id" in c}
    in_criteria, orphans, unknown = False, [], []
    for line in story.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_criteria = "acceptance criteria" in line.lower()
            continue
        if not in_criteria or not CHECKBOX.match(line.strip()):
            continue
        ref = CASE_REF.search(line)
        if not ref:
            orphans.append(line.strip())
        elif ref.group(1) not in known:
            unknown.append(f"{line.strip()} -> {ref.group(1)}")
    assert not orphans, f"{story.stem}: checkboxes with no (case: ID):\n  " + "\n  ".join(orphans)
    assert not unknown, f"{story.stem}: cases cited but missing from the cases file:\n  " + "\n  ".join(unknown)
