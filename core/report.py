"""The report Legal attaches: built as data first, then printed as Markdown.

`build_report` returns a plain dict, and that dict is the JSON file, with the SBOM's text raw.
`to_markdown` derives the Markdown from the same dict and is the only place SBOM text is escaped
(STORY-003 DR-7, security review C4): component names, versions and reasons come from a file anyone
can write, so they are data, never markup.

Escaping, in order:
- every control, format or separator character (ANSI escapes, newlines, bidi overrides, U+2028)
  becomes a visible `\\uXXXX`, so no text can start a new table row or recolour a terminal;
- Markdown syntax is backslash-escaped, so `|` stays inside its cell and `[x](y)` is not a link;
- a URL written inside SBOM text is defanged (`https[:]//...`, `www[.]`), because GitHub-flavoured
  Markdown turns a bare URL into a link even when every bracket is escaped.
The only links in the report are source links, already limited to `https` by the parser (DR-6),
written as `<...>` autolinks with the characters that could end one percent-encoded.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from core.component import Component, JSONObject
from core.policy import ALLOW, REJECT, REVIEW
from core.review import ReviewError, ReviewState, decision_key
from core.sbom import Product

_UNSAFE_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}
_MARKDOWN = "\\|*_[]<>#`~!"
# Characters an https URL may keep as they are; everything else (space, <, >, |, quotes,
# backslash, control and non-ASCII) is percent-encoded so the autolink cannot end early.
_URL_SAFE = ":/?#@!$&'()*+,;=%-._~"


def safe_text(text: str) -> str:
    """Text with every control, format or separator character shown as `\\uXXXX`. For terminals too."""
    return "".join(f"\\u{ord(ch):04x}" if unicodedata.category(ch) in _UNSAFE_CATEGORIES else ch for ch in text)


def md_cell(text: str | None) -> str:
    if text is None or text == "":
        return "—"
    out = safe_text(text)
    out = "".join("\\" + ch if ch in _MARKDOWN else ch for ch in out)
    return out.replace("://", "[:]//").replace("www.", "www[.]")


def md_link(url: str | None) -> str:
    if not url:
        return "none declared"
    return "<" + quote(url, safe=_URL_SAFE) + ">"


def _row(state: ReviewState, component: Component) -> JSONObject:
    return {
        "identity": state.identity,
        "name": component.name,
        "version": component.version,
        "verdict": state.final_verdict,
        "decided_verdict": state.decided_verdict,
        "reason": state.reason,
        "source_url": state.source_url,
        "status": state.status,
        "decision_id": state.decision_id,
        "reviews": [
            {"kind": r.kind, "by": r.by, "reason": r.reason, "verdict": r.verdict, "at": r.at} for r in state.reviews
        ],
    }


def build_report(
    components: list[Component],
    product: Product | None,
    states: dict[str, ReviewState],
    *,
    sbom_sha256: str,
    policy_sha256: str,
    generated_at: str,
    card_keys: Mapping[str, str] | None = None,
) -> JSONObject:
    """The report as data. Raises ReviewError if a component of this SBOM was never scanned.

    `card_keys` (identity → card key) are the keys the scan used for AI models reviewed against their
    cards (STORY-002 DR-5); the caller computes them the same way the scan did.
    """
    by_key = {s.key: s for s in states.values()}  # file order: a later decision for a key wins
    rows: list[tuple[tuple[str, str], JSONObject]] = []
    for c in components:
        key = decision_key(c, policy_sha256, (card_keys or {}).get(c.identity))
        state = by_key.get(key)
        if state is None:
            raise ReviewError(f"{safe_text(c.identity)} has no recorded decision under this policy: run scan first")
        rows.append(((c.identity, key), _row(state, c)))
    rows.sort(key=lambda r: r[0])
    counts = {ALLOW: 0, REVIEW: 0, REJECT: 0, "pending": 0}
    for _, row in rows:
        counts[row["verdict"]] += 1
        counts["pending"] += row["status"] == "pending"
    return {
        "generated_at": generated_at,
        "sbom_sha256": sbom_sha256,
        "policy_sha256": policy_sha256,
        "product": None if product is None else {"name": product.name, "version": product.version},
        "counts": counts,
        "components": [row for _, row in rows],
    }


def _product_line(product: Any) -> str:
    if product is None:
        return "- Product: none identified, so every package in the SBOM was reviewed."
    name = md_cell(product["name"]) + (f"@{md_cell(product['version'])}" if product.get("version") else "")
    return f"- Product (the package this SBOM describes, left out of the review): {name}"


def to_markdown(report: JSONObject) -> str:
    comps = report["components"]
    counts = report["counts"]
    lines = [
        "# Open-source license review",
        "",
        f"- SBOM sha256: `{report['sbom_sha256']}`",
        f"- Policy sha256: `{report['policy_sha256']}`",
        f"- Generated: {report['generated_at']}",
        _product_line(report["product"]),
        "",
        f"Counts cover the {len(comps)} reviewed components; the product is not one of them.",
        "",
        "| Verdict | Count |",
        "|---|---|",
        *(f"| {k} | {counts[k]} |" for k in (ALLOW, REVIEW, REJECT)),
        f"| pending review | {counts['pending']} |",
        "",
        "## Components",
        "",
        "| Component | Version | Verdict | Status | Reason | Source |",
        "|---|---|---|---|---|---|",
    ]
    for c in comps:
        # A reviewed row says so in the row itself: "Reject" next to "Apache-2.0 is allowed" reads as
        # a contradiction unless the cell shows the decided verdict and who changed it.
        verdict = (
            c["verdict"] if c["verdict"] == c["decided_verdict"] else f"{c['verdict']} (decided {c['decided_verdict']})"
        )
        reason = md_cell(c["reason"])
        if c["reviews"]:
            last = c["reviews"][-1]
            reason += f"; {'overridden' if last['kind'] == 'override' else 'approved'} by {md_cell(last['by'])}"
        cells = [md_cell(c["name"]), md_cell(c["version"]), verdict, c["status"], reason]
        lines.append("| " + " | ".join([*cells, md_link(c["source_url"])]) + " |")
    reviewed = [c for c in comps if c["reviews"]]
    lines += ["", "## Reviewer decisions", ""]
    if not reviewed:
        lines.append("None yet.")
    for c in reviewed:
        lines.append(f"- {md_cell(c['name'])} {md_cell(c['version'])} (decided: {c['decided_verdict']})")
        for r in c["reviews"]:
            what = f"overridden to {r['verdict']}" if r["kind"] == "override" else f"approved as {r['verdict']}"
            why = f": {md_cell(r['reason'])}" if r["reason"] else ""
            lines.append(f"  - {r['at']} {what} by {md_cell(r['by'])}{why}")
    return "\n".join(lines) + "\n"
