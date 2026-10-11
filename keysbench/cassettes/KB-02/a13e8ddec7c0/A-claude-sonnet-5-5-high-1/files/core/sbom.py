"""CycloneDX (1.5/1.6) and SPDX (2.3) JSON into one component list.

The product the SBOM describes (CycloneDX `metadata.component`, SPDX package
the document DESCRIBES) is not one of its components and is left out. A
document this module does not recognise, or one with no components, raises
`FormatError`: an empty result would read as "nothing to review".
"""

from __future__ import annotations

import re

from core.component import Component, JSONObject
from core.license_expr import And, ParseError, parse, to_text
from core.purl import parse_purl, url_for


class FormatError(ValueError):
    pass


_SPDX_EMPTY = {"", "NOASSERTION", "NONE"}
# Closest to the source code first (CycloneDX 1.6 externalReferences types).
_REF_PRIORITY = ("vcs", "source-distribution", "distribution", "website")


def _first_url(*candidates: object) -> str | None:
    """DR-7, shared by both formats: the first candidate that is a real link.

    Blank and SPDX `NOASSERTION`/`NONE` values are skipped, and the VCS prefix
    (`git+https://...`, common in both CycloneDX `vcs` refs and SPDX
    `downloadLocation`) is stripped so the result opens in a browser.
    """
    for url in candidates:
        if not isinstance(url, str) or url.strip().upper() in _SPDX_EMPTY:
            continue
        url = url.strip()
        return url[4:] if url.startswith("git+") else url
    return None


def _licenseref(name: str) -> str:
    return "LicenseRef-" + (re.sub(r"[^A-Za-z0-9.]+", "-", name).strip("-") or "unnamed")


# ── CycloneDX ───────────────────────────────────────────────────────────────


def _acknowledgement(entry: JSONObject) -> str | None:
    # CycloneDX 1.6: on an expression entry it sits on the entry, on a license entry inside `license`.
    return entry.get("acknowledgement") or (entry.get("license") or {}).get("acknowledgement")


def _cdx_license(entries: object) -> str | None:
    if not isinstance(entries, list) or not entries:
        return None
    entries = [e for e in entries if isinstance(e, dict)]
    # A verified conclusion overrides the authors' declarations (STORY-001 DR-5), as in SPDX.
    concluded = [e for e in entries if _acknowledgement(e) == "concluded"]
    terms: list[str] = []
    for entry in concluded or entries:
        lic = entry.get("license") or {}
        value = entry.get("expression") or (lic.get("id") if isinstance(lic, dict) else None)
        name = lic.get("name") if isinstance(lic, dict) else None
        # A license value that is not text is a malformed SBOM: say so (DR-8) instead of crashing
        # later with an untyped error or guessing (security scan C15).
        for field in (value, name):
            if field is not None and not isinstance(field, str):
                raise FormatError(f"license value must be text, got {type(field).__name__}")
        if value:
            terms.append(value)
        elif name:
            terms.append(_licenseref(name))
    if not terms:
        return None
    if len(terms) == 1:
        return terms[0]
    # Each entry is parsed on its own and the TREES are combined (DR-5, security scan C1). Joining
    # the raw strings let one entry rewrite another: "x) OR (MIT" next to GPL read as "... OR MIT".
    trees = []
    for term in terms:
        try:
            trees.append(parse(term))
        except ParseError:
            return term  # does not parse on its own, so decide() makes the component Needs review
    return to_text(And(tuple(trees)))


def _cdx_source(c: JSONObject) -> str | None:
    refs = {r.get("type"): r.get("url") for r in c.get("externalReferences") or [] if isinstance(r, dict)}
    return _first_url(*(refs.get(kind) for kind in _REF_PRIORITY), url_for(c.get("purl")))


def _cdx_flatten(components: object, out: list[JSONObject]) -> None:
    if not isinstance(components, list):
        raise FormatError("CycloneDX 'components' must be a list")
    for c in components:
        if isinstance(c, dict):
            out.append(c)
            if "components" in c:
                _cdx_flatten(c["components"], out)


def _parse_cyclonedx(doc: JSONObject) -> list[Component]:
    flat: list[JSONObject] = []
    metadata = doc.get("metadata")
    product = metadata.get("component") if isinstance(metadata, dict) else None
    # The product itself is not reviewed, but its sub-components (at any depth) are.
    if isinstance(product, dict) and "components" in product:
        _cdx_flatten(product["components"], flat)
    _cdx_flatten(doc.get("components", []), flat)
    out = []
    for c in flat:
        purl = c.get("purl")
        out.append(
            Component(
                ref=c.get("bom-ref") or purl or f"{c.get('name')}@{c.get('version', '')}",
                name=str(c.get("name", "")),
                version=c.get("version"),
                type=str(c.get("type", "library")),
                purl=purl,
                license_expression=_cdx_license(c.get("licenses")),
                source_url=_cdx_source(c),
            )
        )
    return out


# ── SPDX ────────────────────────────────────────────────────────────────────


def _spdx_value(v: object) -> str | None:
    return None if not isinstance(v, str) or v.strip().upper() in _SPDX_EMPTY else v.strip()


def _spdx_license(p: JSONObject) -> str | None:
    """DR-5: concluded, then declared, but only when nobody concluded anything (NOASSERTION).

    A concluded NONE is a verified "no license is available" (SPDX 2.3 § 7.13); falling back to the
    author's declaration would replace a verified negative with a claim (security scan C2).
    """
    concluded = p.get("licenseConcluded")
    if isinstance(concluded, str) and concluded.strip().upper() == "NONE":
        return None
    return _spdx_value(concluded) or _spdx_value(p.get("licenseDeclared"))


# Relationships in which the related element is part of, or a dependency of, another package.
_INBOUND = {"DEPENDS_ON", "CONTAINS", "DYNAMIC_LINK", "STATIC_LINK", "HAS_PREREQUISITE", "GENERATES"}
_OUTBOUND = {"DEPENDENCY_OF", "CONTAINED_BY", "PREREQUISITE_FOR", "GENERATED_FROM"}


def _spdx_product(doc: JSONObject) -> str | None:
    """DR-9: the one package to leave out as "the product", or None to review every package.

    Only a single described package counts, and only if no other package depends on it or contains
    it. An extra DESCRIBES (or a described dependency) therefore cannot hide anything (scan C3).
    """
    doc_id = doc.get("SPDXID")
    described = {d for d in doc.get("documentDescribes") or [] if isinstance(d, str)}
    for r in doc.get("relationships") or []:
        if (
            isinstance(r, dict)
            and doc_id
            and r.get("spdxElementId") == doc_id
            and r.get("relationshipType") == "DESCRIBES"
            and isinstance(r.get("relatedSpdxElement"), str)
        ):
            described.add(r["relatedSpdxElement"])
    if len(described) != 1:
        return None
    (product,) = described
    for r in doc.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        kind, src, dst = r.get("relationshipType"), r.get("spdxElementId"), r.get("relatedSpdxElement")
        if (kind in _INBOUND and dst == product) or (kind in _OUTBOUND and src == product):
            return None
    return product


def _parse_spdx(doc: JSONObject) -> list[Component]:
    packages = doc.get("packages", [])
    if not isinstance(packages, list):
        raise FormatError("SPDX 'packages' must be a list")
    product = _spdx_product(doc)
    out = []
    for p in packages:
        if not isinstance(p, dict) or (product is not None and p.get("SPDXID") == product):
            continue
        purl = next(
            (r.get("referenceLocator") for r in p.get("externalRefs") or [] if r.get("referenceType") == "purl"), None
        )
        parsed = parse_purl(purl)
        out.append(
            Component(
                ref=p.get("SPDXID") or purl or f"{p.get('name')}@{p.get('versionInfo', '')}",
                name=str(p.get("name", "")),
                version=p.get("versionInfo"),
                type="machine-learning-model" if parsed and parsed.type == "huggingface" else "library",
                purl=purl,
                license_expression=_spdx_license(p),
                source_url=_first_url(url_for(purl), p.get("downloadLocation"), p.get("homepage")),
            )
        )
    return out


# ── entry point ─────────────────────────────────────────────────────────────


def parse_sbom(doc: object) -> list[Component]:
    if not isinstance(doc, dict):
        raise FormatError("an SBOM must be a JSON object")
    if "bomFormat" in doc and "spdxVersion" in doc:
        raise FormatError("the document carries both formats (bomFormat and spdxVersion): it is ambiguous")
    if doc.get("bomFormat") == "CycloneDX":
        components = _parse_cyclonedx(doc)
    elif str(doc.get("spdxVersion", "")).startswith("SPDX-"):
        components = _parse_spdx(doc)
    else:
        raise FormatError("unknown SBOM format: expected bomFormat=CycloneDX or an spdxVersion")
    if not components:
        raise FormatError("the SBOM has no components")
    return components
