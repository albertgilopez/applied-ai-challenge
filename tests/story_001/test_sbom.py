"""T5: CycloneDX and SPDX parsing into one component list (STORY-001 DR-5..DR-8)."""
from pathlib import Path

import pytest
import yaml

from core.sbom import FormatError, parse_sbom

CASES = {c["id"]: c for c in yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "stories" / "STORY-001.cases.yaml").read_text(encoding="utf-8"))}


def cdx(*components, **extra):
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": list(components), **extra}


def spdx(*packages, **extra):
    return {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "packages": list(packages), **extra}


def pkg(name="p", **kw):
    return {"SPDXID": f"SPDXRef-{name}", "name": name, "versionInfo": "1.0", "downloadLocation": "NOASSERTION", **kw}


def test_several_cyclonedx_licenses_combine_with_and():  # S1-15
    case = CASES["S1-15"]
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "licenses": case["cyclonedx_licenses"]}))
    assert c.license_expression == "(MIT) AND (GPL-3.0-only)"


def test_a_cyclonedx_expression_is_used_as_is():
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "licenses": [{"expression": "MIT OR Apache-2.0"}]}))
    assert c.license_expression == "MIT OR Apache-2.0"


def test_a_name_only_license_becomes_a_licenseref():  # DR-4
    [c] = parse_sbom(cdx({"type": "library", "name": "x",
                          "licenses": [{"license": {"name": "Llama 3.1 Community License"}}]}))
    assert c.license_expression == "LicenseRef-Llama-3.1-Community-License"


@pytest.mark.parametrize("row", CASES["S1-16"]["rows"], ids=lambda r: f"{r['licenseConcluded']}/{r['licenseDeclared']}")
def test_spdx_concluded_then_declared(row):  # S1-16
    [c] = parse_sbom(spdx(pkg(licenseConcluded=row["licenseConcluded"], licenseDeclared=row["licenseDeclared"])))
    expected = None if row["expected"] == "Needs review" else "MIT"
    assert c.license_expression == expected


def test_nested_cyclonedx_components_are_flattened():  # S1-17
    child = lambda n: {"type": "library", "name": n}
    parsed = parse_sbom(cdx({"type": "library", "name": "parent", "components": [child("a"), child("b")]}))
    assert sorted(c.name for c in parsed) == ["a", "b", "parent"]


def test_the_described_product_is_not_a_component():
    product = {"type": "application", "name": "our-product"}
    assert [c.name for c in parse_sbom(cdx({"type": "library", "name": "lib"}, metadata={"component": product}))] == ["lib"]
    doc = spdx(pkg("product"), pkg("lib"),
               relationships=[{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                               "relatedSpdxElement": "SPDXRef-product"}])
    assert [c.name for c in parse_sbom(doc)] == ["lib"]


def test_cyclonedx_source_link_priority():  # S1-18
    row = CASES["S1-18"]["rows"][0]
    [c] = parse_sbom(cdx({"type": "library", "name": "x", "purl": "pkg:pypi/x@1",
                          "externalReferences": row["externalReferences"]}))
    assert c.source_url == row["expected"]


def test_spdx_falls_back_to_homepage():  # S1-18
    row = CASES["S1-18"]["rows"][-1]
    [c] = parse_sbom(spdx(pkg(downloadLocation=row["downloadLocation"], homepage=row["homepage"])))
    assert c.source_url == row["expected"]


def test_spdx_purl_comes_from_external_refs_and_marks_ai_models():  # DR-6
    model = pkg("m", externalRefs=[{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                                    "referenceLocator": "pkg:huggingface/mistralai/Mistral-7B-v0.1"}])
    [c] = parse_sbom(spdx(model))
    assert c.is_ai_model and c.source_url == "https://huggingface.co/mistralai/Mistral-7B-v0.1"


def test_cyclonedx_marks_ai_models_by_type():  # DR-6
    [c] = parse_sbom(cdx({"type": "machine-learning-model", "name": "m"}))
    assert c.is_ai_model


@pytest.mark.parametrize("doc, message", [
    ({"foo": 1}, "unknown SBOM format"),            # S1-19
    (cdx(), "no components"),
    (spdx(), "no components"),
    ({"bomFormat": "CycloneDX", "components": "nope"}, "must be a list"),
    ([], "must be a JSON object"),
])
def test_bad_documents_raise(doc, message):
    with pytest.raises(FormatError, match=message):
        parse_sbom(doc)
