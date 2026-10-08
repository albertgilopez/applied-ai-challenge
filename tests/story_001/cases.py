"""STORY-001 cases and the policy they assume, loaded once for every test module."""

from functools import cache
from pathlib import Path

import yaml

from core.policy import Policy

STORIES = Path(__file__).resolve().parents[2] / "stories"


@cache
def load_cases(story: str) -> dict[str, dict]:
    """Cases of `stories/<story>.cases.yaml`, by id."""
    rows = yaml.safe_load((STORIES / f"{story}.cases.yaml").read_text(encoding="utf-8"))
    return {c["id"]: c for c in rows}


CASES = load_cases("STORY-001")

# The policy written in the header of the cases file (and in samples/policy.yaml).
POLICY = Policy.from_dict(
    {
        "allowed": ["MIT", "Apache-2.0", "BSD-3-Clause", "GPL-2.0-only WITH Classpath-exception-2.0"],
        "review": ["LGPL-2.1-only", "MPL-2.0"],
        "rejected": ["GPL-3.0-only", "AGPL-3.0-only"],
    }
)
