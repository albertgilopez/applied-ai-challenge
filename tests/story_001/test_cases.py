"""STORY-001 cases run against the real code, straight from stories/STORY-001.cases.yaml.

One test per case id, so a failure names the acceptance criterion it breaks.
Cases that need SBOM parsing or the sample files live in test_sbom.py and
test_samples.py; this file covers the license decision.
"""

import pytest

from core.component import Component
from core.decide import decide
from core.policy import Policy
from tests.story_001.cases import CASES as BY_ID
from tests.story_001.cases import POLICY

LICENSE_CASES = [
    "S1-01",
    "S1-02",
    "S1-03",
    "S1-04",
    "S1-05",
    "S1-06",
    "S1-07",
    "S1-08",
    "S1-10",
    "S1-11",
    "S1-12",
    "S1-13",
    "S1-14",
]


def _rows(case):
    return case.get("rows") or [case]


def _component(row, case_id):
    source = row.get("source", "https://example.org/src")
    return Component(
        ref=case_id,
        name="pkg",
        version="1.0",
        type="library",
        purl=None,
        license_expression=row.get("license"),
        source_url=source,
    )


@pytest.mark.parametrize("case_id", LICENSE_CASES)
def test_license_case(case_id):
    for row in _rows(BY_ID[case_id]):
        d = decide(_component(row, case_id), POLICY)
        assert d.verdict == row["expected"], f"{case_id} {row.get('license')!r}: {d}"
        if "reason_contains" in row:
            assert row["reason_contains"] in d.reason, f"{case_id}: reason was {d.reason!r}"


def test_the_reason_names_the_id_that_decided():
    d = decide(_component({"license": "MIT AND GPL-3.0-only"}, "x"), POLICY)
    assert d.verdict == "Reject" and "GPL-3.0-only" in d.reason


def test_a_missing_license_is_never_allowed_even_with_a_permissive_policy():  # DR-1
    lax = Policy.from_dict({"allowed": ["MIT"]})
    for empty in (None, "", "   "):
        assert decide(_component({"license": empty}, "x"), lax).verdict == "Needs review"
