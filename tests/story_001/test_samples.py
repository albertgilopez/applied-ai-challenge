"""T6: the sample files, the file adapter, and S1-09 (both formats agree)."""
from pathlib import Path

import pytest

import samples.build_samples as build
from app.files import MAX_POLICY_BYTES, load_policy, load_sbom
from core.decide import decide
from core.policy import PolicyError
from core.sbom import FormatError
from tests.story_001.test_cases import POLICY

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_both_formats_yield_the_same_components_and_verdicts():  # S1-09
    cdx = {c.identity: c for c in load_sbom(SAMPLES / "sbom.cdx.json")}
    spdx = {c.identity: c for c in load_sbom(SAMPLES / "sbom.spdx.json")}
    assert cdx.keys() == spdx.keys()
    assert len(cdx) >= 10 and sum(c.is_ai_model for c in cdx.values()) >= 2
    policy = load_policy(SAMPLES / "policy.yaml")
    for key in cdx:
        assert cdx[key].license_expression == spdx[key].license_expression, key
        assert cdx[key].is_ai_model == spdx[key].is_ai_model, key
        assert decide(cdx[key], policy).verdict == decide(spdx[key], policy).verdict, key


def test_the_samples_are_what_the_builder_produces():
    import json
    assert json.loads((SAMPLES / "sbom.cdx.json").read_text(encoding="utf-8")) == build.cyclonedx()
    assert json.loads((SAMPLES / "sbom.spdx.json").read_text(encoding="utf-8")) == build.spdx()


def test_the_sample_policy_is_the_one_the_cases_assume():
    assert load_policy(SAMPLES / "policy.yaml") == POLICY


def test_the_sample_covers_every_verdict():
    policy = load_policy(SAMPLES / "policy.yaml")
    verdicts = {decide(c, policy).verdict for c in load_sbom(SAMPLES / "sbom.cdx.json")}
    assert verdicts == {"Allow", "Needs review", "Reject"}


def test_invalid_json_is_a_format_error(tmp_path):  # S1-19
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(FormatError, match="not valid JSON"):
        load_sbom(bad)


def test_deeply_nested_json_is_a_format_error(tmp_path):
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    with pytest.raises(FormatError):
        load_sbom(deep)


def test_an_oversized_policy_is_refused_before_parsing(tmp_path):
    big = tmp_path / "policy.yaml"
    big.write_text("allowed:\n" + "  - MIT\n" * (MAX_POLICY_BYTES // 8 + 1), encoding="utf-8")
    with pytest.raises(PolicyError, match="limit"):
        load_policy(big)


def test_a_bare_no_in_the_policy_is_refused(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text("allowed:\n  - MIT\n  - no\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="not a license id"):
        load_policy(p)
