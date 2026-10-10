"""STORY-002, the pure part: grounding, mapping and the verdict (core/model_card.py).

The model's answer is scripted here; what is under test is what the code does with it. Each case comes
from stories/STORY-002.cases.yaml, so a case that is edited there is the case that runs here.
"""

from pathlib import Path

import pytest
import yaml

from app.files import load_policy
from core.component import Component
from core.model_card import Extraction, Restriction, card_license, evidence_digest, ground, review_model

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "samples" / "model-cards"
POLICY = load_policy(ROOT / "samples" / "policy.yaml")
CASES = {c["id"]: c for c in yaml.safe_load((ROOT / "stories" / "STORY-002.cases.yaml").read_text(encoding="utf-8"))}


def card(name: str) -> str:
    return (CARDS / f"{name}.md").read_text(encoding="utf-8")


def extraction(answer: dict) -> Extraction:
    return Extraction(
        license_id=answer["license_id"],
        quote=answer["quote"],
        restrictions=tuple(Restriction(r["text"], r["quote"]) for r in answer.get("restrictions", [])),
    )


def model(license_expression: str | None = None) -> Component:
    return Component(
        ref="m",
        name="m",
        version=None,
        type="machine-learning-model",
        purl="pkg:huggingface/org/m",
        license_expression=license_expression,
        source_url="https://huggingface.co/org/m",
    )


def run(case_id: str, answer: dict | None = None, sbom_license: str | None = None):
    c = CASES[case_id]
    return review_model(model(sbom_license), extraction(answer or c["model_answer"]), card(c["card"]), POLICY)


def test_s2_01_permissive_card_is_allowed_with_its_quote():
    review = run("S2-01")
    assert review.decision.verdict == "Allow"
    assert review.license == "Apache-2.0"
    assert review.grounded


def test_s2_02_custom_license_needs_review_and_lists_restrictions():
    review = run("S2-02")
    assert review.decision.verdict == "Needs review"
    assert review.license == "LicenseRef-llama3.1"
    assert len(review.restrictions) == 2
    assert "700 million" in review.decision.reason


def test_s2_03_a_quote_that_is_not_in_the_card_is_grounding_failed():
    review = run("S2-03")
    assert review.decision.verdict == "Needs review"
    assert "grounding failed" in review.decision.reason
    assert not review.grounded


def test_s2_04_no_license_found_is_never_allow():
    review = run("S2-04")
    assert review.decision.verdict == "Needs review"
    assert "no license found in model card" in review.decision.reason


def test_s2_05_a_rejected_card_license_is_reject():
    review = run("S2-05")
    assert review.decision.verdict == "Reject"
    assert review.license == "AGPL-3.0-only"


@pytest.mark.parametrize("row", CASES["S2-08"]["rows"], ids=["trivial-quote", "quote-for-another-id"])
def test_s2_08_a_quote_must_name_the_license_it_grounds(row):
    review = run("S2-08", answer=row["model_answer"])
    assert review.decision.verdict == row["expected"]["verdict"]
    assert row["expected"]["reason_contains"] in review.decision.reason


@pytest.mark.parametrize("row", CASES["S2-09"]["rows"], ids=lambda r: f"{r['sbom_license']}+{r['card_license']}")
def test_s2_09_the_worse_of_sbom_and_card_wins(row):
    answer = {"license_id": row["card_license"], "quote": f"license: {row['card_license']}", "restrictions": []}
    text = f"---\nlicense: {row['card_license']}\n---\n# m\n"
    review = review_model(model(row["sbom_license"]), extraction(answer), text, POLICY)
    assert review.decision.verdict == row["expected"]


def test_s2_11_a_restriction_without_a_grounded_quote_is_dropped_and_counted():
    review = run("S2-11")
    assert len(review.restrictions) == 1
    assert CASES["S2-11"]["expected"]["reason_contains"] in review.decision.reason


def test_grounding_ignores_whitespace_and_case_but_not_words():
    text = "Licensed under the  Apache-2.0\nlicense."
    assert ground("licensed under the apache-2.0 license.", text, "apache-2.0")
    assert not ground("licensed under the apache-2.0 licence.", text, "apache-2.0")
    assert not ground("", text, "apache-2.0")
    assert not ground(None, text, "apache-2.0")


@pytest.mark.parametrize(
    ("hf_id", "spdx"),
    [
        ("apache-2.0", "Apache-2.0"),
        ("MIT", "MIT"),
        ("agpl-3.0", "AGPL-3.0-only"),
        ("gpl-3.0", "GPL-3.0-only"),
        ("llama3.1", "LicenseRef-llama3.1"),
        ("other", "LicenseRef-other"),
        ("gemma", "LicenseRef-gemma"),
        ("evil) OR (MIT", "LicenseRef-unknown"),
    ],
)
def test_card_ids_map_to_spdx_or_a_custom_reference(hf_id, spdx):
    assert card_license(hf_id) == spdx


def test_the_evidence_digest_changes_with_the_card_and_with_the_answer():
    text = card("mistralai__Mistral-7B-v0.1")
    a = extraction(CASES["S2-01"]["model_answer"])
    base = evidence_digest(text, a)
    assert evidence_digest(text, a) == base
    assert evidence_digest(text + "\nnew line", a) != base
    assert evidence_digest(text, Extraction("mit", "license: mit", ())) != base
