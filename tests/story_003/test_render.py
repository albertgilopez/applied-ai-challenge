"""STORY-003 rules that live in the pure core: the source-link scheme, the product, the escaping."""

import json
import re
import unicodedata
from pathlib import Path

import pytest

from app.files import load_policy, load_sbom
from core.component import Component
from core.decide import decide
from core.report import build_report, md_link, to_markdown
from core.review import decision_record, fold
from core.sbom import Product, parse_sbom, read_sbom
from tests.story_001.cases import load_cases

CASES = load_cases("STORY-003")
SAMPLES = Path(__file__).resolve().parents[2] / "samples"
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def cdx_with_source(url, **component):
    c = {"type": "library", "name": "x", "version": "1.0", **component}
    if url is not None:
        c["externalReferences"] = [{"type": "vcs", "url": url}]
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [c]}


# ── T1: only https is a source link (DR-6, security review C5) ──────────────


@pytest.mark.parametrize("row", CASES["S3-10"]["rows"], ids=lambda r: r["source"][:20])
def test_only_https_is_a_source_link(row):  # S3-10
    [c] = parse_sbom(cdx_with_source(row["source"]))
    expected = None if row["expected"] == "none declared" else row["expected"]
    assert c.source_url == expected


def test_a_refused_scheme_falls_through_to_the_next_candidate():  # S3-10
    [c] = parse_sbom(cdx_with_source("javascript:alert(1)", purl="pkg:pypi/requests@2.32.3"))
    assert c.source_url == "https://pypi.org/project/requests/2.32.3/"


def test_scheme_is_case_insensitive():  # S3-10
    [c] = parse_sbom(cdx_with_source("HTTPS://github.com/o/r"))
    assert c.source_url == "HTTPS://github.com/o/r"


# ── T1: the product left out is returned, not lost (DR-8) ──────────────────


def test_cyclonedx_sample_names_its_product():  # S3-12
    doc = read_sbom(json.loads((SAMPLES / "sbom.cdx.json").read_text(encoding="utf-8")))
    assert doc.product == Product("sample-instrument-software", "3.2.0")
    assert doc.components == parse_sbom(json.loads((SAMPLES / "sbom.cdx.json").read_text(encoding="utf-8")))


def test_spdx_sample_names_its_product():  # S3-12
    doc = read_sbom(json.loads((SAMPLES / "sbom.spdx.json").read_text(encoding="utf-8")))
    assert doc.product is not None and doc.product.name == "sample-instrument-software"


def test_spdx_with_two_described_packages_has_no_product():  # S3-12
    pkg = lambda n: {"SPDXID": f"SPDXRef-{n}", "name": n, "versionInfo": "1.0"}  # noqa: E731
    doc = read_sbom(
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "documentDescribes": ["SPDXRef-a", "SPDXRef-b"],
            "packages": [pkg("a"), pkg("b")],
        }
    )
    assert doc.product is None
    assert len(doc.components) == 2


# ── T4: the report, built as data and printed escaped (DR-7, DR-8) ──────────


def report_for(components, product=None, policy=None):
    policy = policy or load_policy(SAMPLES / "policy.yaml")
    digest = policy.digest()
    ledger = [
        {"id": f"d{i}", "at": "t", **decision_record(c, decide(c, policy), digest)} for i, c in enumerate(components)
    ]
    return build_report(
        components, product, fold(ledger), sbom_sha256="s" * 64, policy_sha256=digest, generated_at="now"
    )


def component_rows(markdown):
    lines = markdown.splitlines()
    start = lines.index("| Component | Version | Verdict | Status | Reason | Source |") + 2
    end = next(i for i in range(start, len(lines)) if not lines[i].startswith("|"))
    return lines[start:end]


def test_hostile_sbom_text_cannot_break_the_report():  # S3-11
    case = CASES["S3-11"]
    spec = case["component"]
    c = Component("ref", spec["name"], spec["version"], "library", None, spec["license"], spec["source"])
    report = report_for([c])
    md = to_markdown(report)
    rows = component_rows(md)
    assert len(rows) == case["expected"]["markdown_component_rows"]
    assert len(UNESCAPED_PIPE.findall(rows[0])) == 7  # 6 cells -> 7 borders, none of them from the name
    assert not any(unicodedata.category(ch) in ("Cc", "Cf") for ch in md.replace("\n", ""))
    assert "https://evil" not in md  # neither a Markdown link nor a bare URL a renderer would link
    assert report["components"][0]["name"] == spec["name"]  # the JSON keeps the raw text


def test_bidi_override_is_shown_not_applied():  # S3-11
    c = Component("ref", "safe‮exe.txt", "1.0", "library", None, "MIT", "https://github.com/o/r")
    md = to_markdown(report_for([c]))
    assert "‮" not in md and "\\u202e" in md


def test_a_source_link_cannot_end_its_autolink_early():  # S3-11
    assert md_link("https://h.example/a b|c>d") == "<https://h.example/a%20b%7Cc%3Ed>"
    assert md_link(None) == "none declared"


def test_counts_sum_and_every_row_has_a_source_or_none_declared():  # S3-04
    components = load_sbom(SAMPLES / "sbom.cdx.json")
    report = report_for(components)
    counts = report["counts"]
    assert counts["Allow"] + counts["Needs review"] + counts["Reject"] == len(components)
    assert counts["pending"] == len(components)
    for row in component_rows(to_markdown(report)):
        source = UNESCAPED_PIPE.split(row)[-2].strip()
        assert source == "none declared" or source.startswith("<https://"), row


def test_an_overridden_row_shows_the_decided_verdict_and_the_reviewer():  # S3-03
    c = Component("ref", "requests", "2.32.3", "library", None, "Apache-2.0", "https://github.com/psf/requests")
    policy = load_policy(SAMPLES / "policy.yaml")
    digest = policy.digest()
    ledger = [
        {"id": "d0", "at": "t", **decision_record(c, decide(c, policy), digest)},
        {"id": "o1", "at": "t", "kind": "override", "decision": "d0", "verdict": "Reject", "by": "Ana", "reason": "x"},
    ]
    report = build_report([c], None, fold(ledger), sbom_sha256="s", policy_sha256=digest, generated_at="now")
    [row] = component_rows(to_markdown(report))
    assert "Reject (decided Allow)" in row and "overridden by Ana" in row


@pytest.mark.parametrize(
    ("product", "expected"),
    [(Product("sample-instrument-software", "3.2.0"), "sample-instrument-software@3.2.0"), (None, "every package")],
)
def test_the_report_names_the_product_or_says_every_package_was_reviewed(product, expected):  # S3-12
    c = Component("ref", "x", "1.0", "library", None, "MIT", "https://github.com/o/r")
    report = report_for([c], product)
    assert expected in to_markdown(report)
    assert report["product"] == (None if product is None else {"name": product.name, "version": product.version})
