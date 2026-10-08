"""STORY-003 rules that live in the pure core: the source-link scheme, the product, the escaping."""

import json
from pathlib import Path

import pytest

from core.sbom import Product, parse_sbom, read_sbom
from tests.story_001.cases import load_cases

CASES = load_cases("STORY-003")
SAMPLES = Path(__file__).resolve().parents[2] / "samples"


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
