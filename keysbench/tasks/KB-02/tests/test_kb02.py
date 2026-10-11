"""Hidden tests for KB-02: the two tests the real fix added, plus the behaviour around them.

The contestant's code runs in its own process through `kbcall`; only plain JSON comes back.
"""

from kbcall import call


def names(document: dict) -> list:
    return call(f"sorted(c.name for c in core.sbom.parse_sbom({document!r}))", "core.sbom")


def lib(name: str, *children: dict) -> dict:
    c: dict = {"type": "library", "name": name}
    if children:
        c["components"] = list(children)
    return c


def test_a_document_in_both_formats_is_a_format_error():
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "spdxVersion": "SPDX-2.3",
        "components": [lib("x")],
        "packages": [],
    }
    outcome = call(
        "_out",
        "core.sbom",
        setup=(
            "try:\n"
            f"    core.sbom.parse_sbom({doc!r})\n"
            "    _out = 'accepted'\n"
            "except core.sbom.FormatError as e:\n"
            "    _out = 'FormatError: ' + str(e)\n"
        ),
    )
    assert outcome.startswith("FormatError: ")
    assert "both" in outcome


def test_the_products_sub_components_are_reviewed():
    product = {"type": "application", "name": "product", "components": [lib("sub-a"), lib("sub-b", lib("sub-c"))]}
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"component": product},
        "components": [lib("lib")],
    }
    assert names(doc) == ["lib", "sub-a", "sub-b", "sub-c"]


def test_nested_components_are_still_flattened():
    doc = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [lib("a", lib("b", lib("c")))]}
    assert names(doc) == ["a", "b", "c"]


def test_spdx_packages_are_still_read():
    pkg = {"SPDXID": "SPDXRef-p", "name": "p", "versionInfo": "1.0", "downloadLocation": "NOASSERTION"}
    doc = {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "packages": [pkg]}
    assert names(doc) == ["p"]
