"""T5: CycloneDX and SPDX parsing into one component list (STORY-001 DR-5..DR-8)."""

import pytest

from core.decide import decide
from core.sbom import FormatError, parse_sbom
from tests.story_001.cases import CASES, POLICY


def cdx(*components, **extra):
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": list(components), **extra}


def spdx(*packages, **extra):
    return {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "packages": list(packages), **extra}


def pkg(name="p", **kw):
    return {"SPDXID": f"SPDXRef-{name}", "name": name, "versionInfo": "1.0", "downloadLocation": "NOASSERTION", **kw}


def test_several_cyclonedx_licenses_combine_with_and():  # S1-15
    case = CASES["S1-15"]
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "licenses": case["cyclonedx_licenses"]}))
    assert c.license_expression == "MIT AND GPL-3.0-only"
    assert decide(c, POLICY).verdict == case["expected"]


@pytest.mark.parametrize("row", CASES["S1-21"]["rows"], ids=["injection", "or-entry", "allowed-or-entry"])
def test_one_entry_cannot_rewrite_another(row):  # S1-21, security scan C1
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "licenses": row["cyclonedx_licenses"]}))
    d = decide(c, POLICY)
    assert d.verdict == row["expected"], (c.license_expression, d.reason)
    if "reason_contains" in row:
        assert row["reason_contains"] in d.reason


@pytest.mark.parametrize("bad", [{"expression": ["MIT"]}, {"license": {"id": 5}}, {"license": {"name": {"x": 1}}}])
def test_a_license_value_that_is_not_text_is_a_format_error(bad):  # S1-19 / DR-8, security scan C15
    with pytest.raises(FormatError, match="must be text"):
        parse_sbom(cdx({"type": "library", "name": "x", "licenses": [bad]}))


@pytest.mark.parametrize("row", CASES["S1-22"]["rows"], ids=["concluded-none", "concluded-noassertion"])
def test_spdx_concluded_none_is_not_the_declared_license(row):  # S1-22, security scan C2
    [c] = parse_sbom(spdx(pkg(licenseConcluded=row["licenseConcluded"], licenseDeclared=row["licenseDeclared"])))
    assert decide(c, POLICY).verdict == row["expected"]


@pytest.mark.parametrize("row", CASES["S1-23"]["rows"], ids=["two-described", "described-dependency", "product-only"])
def test_describes_cannot_hide_a_dependency(row):  # S1-23, security scan C3
    doc = spdx(
        pkg("product"),
        pkg("lib", licenseConcluded="MIT"),
        {**pkg("gpl", licenseConcluded="GPL-3.0-only"), "name": "gpl-dep"},
        documentDescribes=row["describes"],
        relationships=row["relationships"],
    )
    assert sorted(c.name for c in parse_sbom(doc)) == row["expected_reviewed"]


@pytest.mark.parametrize("row", CASES["S1-20"]["rows"], ids=["concluded-wins", "no-concluded-all-count"])
def test_cyclonedx_concluded_overrides_declared(row):  # S1-20
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "licenses": row["cyclonedx_licenses"]}))
    assert c.license_expression == row["expected"]


def test_a_cyclonedx_expression_is_used_as_is():
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "licenses": [{"expression": "MIT OR Apache-2.0"}]}))
    assert c.license_expression == "MIT OR Apache-2.0"


def test_a_name_only_license_becomes_a_licenseref():  # DR-4
    [c] = parse_sbom(
        cdx({"type": "library", "name": "x", "licenses": [{"license": {"name": "Llama 3.1 Community License"}}]})
    )
    assert c.license_expression == "LicenseRef-Llama-3.1-Community-License"


@pytest.mark.parametrize("row", CASES["S1-16"]["rows"], ids=lambda r: f"{r['licenseConcluded']}/{r['licenseDeclared']}")
def test_spdx_concluded_then_declared(row):  # S1-16
    [c] = parse_sbom(spdx(pkg(licenseConcluded=row["licenseConcluded"], licenseDeclared=row["licenseDeclared"])))
    expected = None if row["expected"] == "Needs review" else "MIT"
    assert c.license_expression == expected


def test_nested_cyclonedx_components_are_flattened():  # S1-17
    def child(name):
        return {"type": "library", "name": name}

    parsed = parse_sbom(cdx({"type": "library", "name": "parent", "components": [child("a"), child("b")]}))
    assert sorted(c.name for c in parsed) == ["a", "b", "parent"]


def test_the_described_product_is_not_a_component():
    product = {"type": "application", "name": "our-product"}
    assert [c.name for c in parse_sbom(cdx({"type": "library", "name": "lib"}, metadata={"component": product}))] == [
        "lib"
    ]
    doc = spdx(
        pkg("product"),
        pkg("lib"),
        relationships=[
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-product",
            }
        ],
    )
    assert [c.name for c in parse_sbom(doc)] == ["lib"]


@pytest.mark.parametrize(
    "row", [r for r in CASES["S1-18"]["rows"] if "externalReferences" in r], ids=lambda r: r["expected"]
)
def test_cyclonedx_source_link_priority(row):  # S1-18
    [c] = parse_sbom(
        cdx({"type": "library", "name": "x", "purl": "pkg:pypi/x@1", "externalReferences": row["externalReferences"]})
    )
    assert c.source_url == row["expected"]


def test_spdx_falls_back_to_homepage():  # S1-18
    row = next(r for r in CASES["S1-18"]["rows"] if "homepage" in r)
    [c] = parse_sbom(spdx(pkg(downloadLocation=row["downloadLocation"], homepage=row["homepage"])))
    assert c.source_url == row["expected"]


def test_spdx_purl_comes_from_external_refs_and_marks_ai_models():  # DR-6
    model = pkg(
        "m",
        externalRefs=[
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": "pkg:huggingface/mistralai/Mistral-7B-v0.1",
            }
        ],
    )
    [c] = parse_sbom(spdx(model))
    assert c.is_ai_model and c.source_url == "https://huggingface.co/mistralai/Mistral-7B-v0.1"


def test_cyclonedx_marks_ai_models_by_type():  # DR-6
    [c] = parse_sbom(cdx({"type": "machine-learning-model", "name": "m"}))
    assert c.is_ai_model


@pytest.mark.parametrize(
    "doc, message",
    [
        ({"foo": 1}, "unknown SBOM format"),  # S1-19
        (cdx(), "no components"),
        (spdx(), "no components"),
        ({"bomFormat": "CycloneDX", "components": "nope"}, "must be a list"),
        ([], "must be a JSON object"),
    ],
)
def test_bad_documents_raise(doc, message):
    with pytest.raises(FormatError, match=message):
        parse_sbom(doc)
