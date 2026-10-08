"""Minimal package URL (purl) support: enough to link a component to its source.

    pkg:<type>/<namespace>/<name>@<version>?<qualifiers>#<subpath>

Only the types this tool links to are mapped; any other type, or a malformed
purl, yields no link rather than a guessed one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, unquote


@dataclass(frozen=True)
class Purl:
    type: str
    namespace: str | None
    name: str
    version: str | None


def parse_purl(text: str | None) -> Purl | None:
    if not text or not text.startswith("pkg:"):
        return None
    body = text[4:].split("#", 1)[0].split("?", 1)[0].strip("/")
    version = None
    if "@" in body.rsplit("/", 1)[-1]:
        body, version = body.rsplit("@", 1)
        version = unquote(version) or None
    parts = [unquote(p) for p in body.split("/") if p]
    if len(parts) < 2:
        return None
    ptype, *namespace, name = parts
    return Purl(ptype.lower(), "/".join(namespace) or None, name, version)


def _pypi(p: Purl) -> str:
    return f"https://pypi.org/project/{p.name}/" + (f"{p.version}/" if p.version else "")


def _npm(p: Purl) -> str:
    full = f"{p.namespace}/{p.name}" if p.namespace else p.name
    return f"https://www.npmjs.com/package/{full}" + (f"/v/{p.version}" if p.version else "")


def _maven(p: Purl) -> str | None:
    if not p.namespace:
        return None
    return f"https://central.sonatype.com/artifact/{p.namespace}/{p.name}" + (f"/{p.version}" if p.version else "")


def _owner_repo(host: str) -> Callable[[Purl], str | None]:
    return lambda p: f"https://{host}/{p.namespace}/{p.name}" if p.namespace else None


_LINKS = {
    "pypi": _pypi,
    "npm": _npm,
    "maven": _maven,
    "github": _owner_repo("github.com"),
    "huggingface": _owner_repo("huggingface.co"),
}


def url_for(text: str | None) -> str | None:
    p = parse_purl(text)
    if p is None or p.type not in _LINKS:
        return None
    url = _LINKS[p.type](p)
    return quote(url, safe=":/@._-~") if url else None
