"""CycloneDX (1.5/1.6) and SPDX (2.3) JSON into one component list.

The product the SBOM describes (CycloneDX `metadata.component`, SPDX package
the document DESCRIBES) is not one of its components and is left out. A
document this module does not recognise, or one with no components, raises
`FormatError`: an empty result would read as "nothing to review".
"""
from __future__ import annotations

import re

from core.component import Component
from core.purl import parse_purl, url_for


class FormatError(ValueError):
    pass


_SPDX_EMPTY = {"", "NOASSERTION", "NONE"}
_REF_PRIORITY = ("vcs", "distribution", "website")


def _licenseref(name: str) -> str:
    return "LicenseRef-" + (re.sub(r"[^A-Za-z0-9.]+", "-", name).strip("-") or "unnamed")


# ── CycloneDX ───────────────────────────────────────────────────────────────

def _cdx_license(entries) -> str | None:
    if not entries:
        return None
    terms = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
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


def _cdx_source(c: dict) -> str | None:
    refs = {r.get("type"): r.get("url") for r in c.get("externalReferences") or [] if isinstance(r, dict)}
    for kind in _REF_PRIORITY:
        if refs.get(kind):
            return refs[kind]
    return url_for(c.get("purl"))


def _cdx_flatten(components, out: list[dict]) -> None:
    if not isinstance(components, list):
        raise FormatError("CycloneDX 'components' must be a list")
    for c in components:
        if isinstance(c, dict):
            out.append(c)
            if "components" in c:
                _cdx_flatten(c["components"], out)


def _parse_cyclonedx(doc: dict) -> list[Component]:
    flat: list[dict] = []
    _cdx_flatten(doc.get("components", []), flat)
    out = []
    for c in flat:
        purl = c.get("purl")
        out.append(Component(
            ref=c.get("bom-ref") or purl or f"{c.get('name')}@{c.get('version', '')}",
            name=str(c.get("name", "")),
            version=c.get("version"),
            type=str(c.get("type", "library")),
            purl=purl,
            license_expression=_cdx_license(c.get("licenses")),
            source_url=_cdx_source(c),
            is_ai_model=c.get("type") == "machine-learning-model",
        ))
    return out


# ── SPDX ────────────────────────────────────────────────────────────────────

def _spdx_value(v) -> str | None:
    return None if not isinstance(v, str) or v.strip().upper() in _SPDX_EMPTY else v.strip()


def _spdx_described(doc: dict) -> set[str]:
    described = set(doc.get("documentDescribes") or [])
    for r in doc.get("relationships") or []:
        if r.get("spdxElementId") == doc.get("SPDXID") and r.get("relationshipType") == "DESCRIBES":
            described.add(r.get("relatedSpdxElement"))
    return described


def _parse_spdx(doc: dict) -> list[Component]:
    packages = doc.get("packages", [])
    if not isinstance(packages, list):
        raise FormatError("SPDX 'packages' must be a list")
    described = _spdx_described(doc)
    out = []
    for p in packages:
        if not isinstance(p, dict) or p.get("SPDXID") in described:
            continue
        purl = next((r.get("referenceLocator") for r in p.get("externalRefs") or []
                     if r.get("referenceType") == "purl"), None)
        download = _spdx_value(p.get("downloadLocation"))
        if download and download.startswith("git+"):
            download = download[4:]
        parsed = parse_purl(purl)
        out.append(Component(
            ref=p.get("SPDXID") or purl or f"{p.get('name')}@{p.get('versionInfo', '')}",
            name=str(p.get("name", "")),
            version=p.get("versionInfo"),
            type="machine-learning-model" if parsed and parsed.type == "huggingface" else "library",
            purl=purl,
            license_expression=_spdx_value(p.get("licenseConcluded")) or _spdx_value(p.get("licenseDeclared")),
            source_url=url_for(purl) or download or _spdx_value(p.get("homepage")),
            is_ai_model=bool(parsed and parsed.type == "huggingface"),
        ))
    return out


# ── entry point ─────────────────────────────────────────────────────────────

def parse_sbom(doc) -> list[Component]:
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
