"""STORY-005 cases run against the real code, straight from stories/STORY-005.cases.yaml."""

from pathlib import Path

import pytest
import yaml

from core.decide import Decision
from core.vulns import apply_vulnerabilities

CASES = {c["id"]: c for c in yaml.safe_load(Path("stories/STORY-005.cases.yaml").read_text(encoding="utf-8"))}


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_vulnerability_case(case_id):
    case = CASES[case_id]
    decision = Decision("ref", case["verdict"], "license reason", "https://example.org/src")
    result = apply_vulnerabilities(decision, case["vulns"])
    assert result.verdict == case["expected"]
    assert case.get("reason_contains", "") in result.reason
