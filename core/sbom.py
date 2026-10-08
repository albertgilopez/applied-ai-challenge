"""CycloneDX (1.5/1.6) and SPDX (2.3) JSON into one component list.

The product the SBOM describes (CycloneDX `metadata.component`, SPDX package
the document DESCRIBES) is not one of its components and is left out. A
document this module does not recognise, or one with no components, raises
`FormatError`: an empty result would read as "nothing to review".
"""

from __future__ import annotations

import re

from core.component import Component, JSONObject
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
    terms = []
    for entry in concluded or entries:
        if entry.get("expression"):
            terms.append(entry["expression"])
            continue
        lic = entry.get("license") or {}
        if lic.get("id"):
            terms.append(lic["id"])
        elif lic.get("name"):
            terms.append(_licenseref(lic["name"]))
    if not terms:
        return None
    return terms[0] if len(terms) == 1 else " AND ".join(f"({t})" for t in terms)


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


def _spdx_described(doc: JSONObject) -> set[str]:
    described = set(doc.get("documentDescribes") or [])
    for r in doc.get("relationships") or []:
        if r.get("spdxElementId") == doc.get("SPDXID") and r.get("relationshipType") == "DESCRIBES":
            described.add(r.get("relatedSpdxElement"))
    return described


def _parse_spdx(doc: JSONObject) -> list[Component]:
    packages = doc.get("packages", [])
    if not isinstance(packages, list):
        raise FormatError("SPDX 'packages' must be a list")
    described = _spdx_described(doc)
    out = []
    for p in packages:
        if not isinstance(p, dict) or p.get("SPDXID") in described:
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
                license_expression=_spdx_value(p.get("licenseConcluded")) or _spdx_value(p.get("licenseDeclared")),
                source_url=_first_url(url_for(purl), p.get("downloadLocation"), p.get("homepage")),
            )
        )
    return out


# ── entry point ─────────────────────────────────────────────────────────────


def parse_sbom(doc: object) -> list[Component]:
    if not isinstance(doc, dict):
        raise FormatError("an SBOM must be a JSON object")
    if doc.get("bomFormat") == "CycloneDX":
        components = _parse_cyclonedx(doc)
    elif str(doc.get("spdxVersion", "")).startswith("SPDX-"):
        components = _parse_spdx(doc)
    else:
        raise FormatError("unknown SBOM format: expected bomFormat=CycloneDX or an spdxVersion")
    if not components:
        raise FormatError("the SBOM has no components")
    return components
