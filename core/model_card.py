"""From what a model read in a model card to a verdict (STORY-002).

The model reads prose; this module decides (DOCTRINE D-03). It checks the model's quotes against the
card as the code loaded it, maps the card's license id to an SPDX id or a custom reference, applies the
policy through `decide.evaluate`, and combines that with what the SBOM declares. Nothing here calls a
model or reads a file.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from core.component import Component
from core.decide import RANK, Decision, decide, evaluate
from core.license_expr import ParseError, parse
from core.policy import REVIEW, Policy

# Hugging Face license ids that are SPDX licenses. Anything else is custom (`LicenseRef-<id>`), which
# the policy sends to review unless it lists it.
HF_TO_SPDX = {
    "apache-2.0": "Apache-2.0",
    "mit": "MIT",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "gpl-2.0": "GPL-2.0-only",
    "gpl-3.0": "GPL-3.0-only",
    "agpl-3.0": "AGPL-3.0-only",
    "lgpl-2.1": "LGPL-2.1-only",
    "lgpl-3.0": "LGPL-3.0-only",
    "mpl-2.0": "MPL-2.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc0-1.0": "CC0-1.0",
    "unlicense": "Unlicense",
}

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,63}")
MIN_RESTRICTION_QUOTE = 12  # characters, after normalising: shorter than a phrase grounds nothing


@dataclass(frozen=True)
class Restriction:
    text: str
    quote: str


@dataclass(frozen=True)
class Extraction:
    """The model's answer, as typed data. `agent/` builds it; nothing here trusts it."""

    license_id: str | None
    quote: str | None
    restrictions: tuple[Restriction, ...] = ()


@dataclass(frozen=True)
class CardReview:
    decision: Decision
    license: str | None  # SPDX id or LicenseRef-<id>, when grounded
    grounded: bool
    restrictions: tuple[Restriction, ...]  # the grounded ones only
    dropped: int  # restrictions whose quote is not in the card


def normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _in_card(quote: str | None, card: str) -> bool:
    return bool(quote and quote.strip()) and normalise(quote or "") in normalise(card)


def ground(quote: str | None, card: str, license_id: str) -> bool:
    """The quote is in the card, and it names the license it is offered for (DR-1).

    "Is in the card" alone grounded a one-word quote; the id inside the quote is what ties the
    evidence to the claim.
    """
    return _in_card(quote, card) and normalise(license_id) in normalise(quote or "")


def _grounded_restriction(r: Restriction, card: str) -> bool:
    return len(normalise(r.quote)) >= MIN_RESTRICTION_QUOTE and _in_card(r.quote, card)


def card_license(license_id: str) -> str:
    key = license_id.strip().casefold()
    if key in HF_TO_SPDX:
        return HF_TO_SPDX[key]
    if _SAFE_ID.fullmatch(license_id.strip()):
        return f"LicenseRef-{license_id.strip()}"
    return "LicenseRef-unknown"  # an id that would not parse as one term is never passed to the parser


def _card_verdict(extraction: Extraction, card: str, policy: Policy) -> tuple[str, str, str | None, bool]:
    if not extraction.license_id:
        return REVIEW, "no license found in model card", None, False
    if not ground(extraction.quote, card, extraction.license_id):
        return REVIEW, "grounding failed: the quote is not in the card or does not name the license", None, False
    spdx = card_license(extraction.license_id)
    try:
        verdict, reason = evaluate(parse(spdx), policy)
    except ParseError:  # pragma: no cover - card_license only returns single, parseable terms
        return REVIEW, f"unparseable card license {spdx!r}", None, False
    return verdict, f"{reason} (quoted: {extraction.quote!r})", spdx, True


def review_model(component: Component, extraction: Extraction | None, card: str, policy: Policy) -> CardReview:
    """`extraction` is None when the model's answer could not be read: that is a review, never an allow."""
    if extraction is None:
        card_verdict, card_reason, spdx, grounded = REVIEW, "the model's answer could not be read", None, False
        extraction = Extraction(None, None, ())
    else:
        card_verdict, card_reason, spdx, grounded = _card_verdict(extraction, card, policy)
    kept = tuple(r for r in extraction.restrictions if _grounded_restriction(r, card))
    dropped = len(extraction.restrictions) - len(kept)

    sbom = decide(component, policy)
    if (component.license_expression or "").strip():
        # A card cannot upgrade what the SBOM declares; it can only add evidence (DR-4).
        verdict = min((sbom.verdict, card_verdict), key=lambda v: RANK[v])
        reason = f"SBOM: {sbom.reason}; model card: {card_reason}"
    else:
        # The SBOM declares nothing: a grounded card license is the license.
        verdict = card_verdict
        reason = f"SBOM: no license declared; model card: {card_reason}"
        if not component.source_url:
            reason += "; no source declared"
    if kept:
        reason += "; restrictions: " + "; ".join(r.text for r in kept)
    if dropped:
        reason += f"; {dropped} restriction{'s' if dropped > 1 else ''} not grounded"
    decision = Decision(component.ref, verdict, reason, component.source_url)
    return CardReview(decision, spdx, grounded, kept, dropped)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def card_key(card: str, prompt_sha256: str, model: str, effort: str) -> str:
    """What a card decision is made from, beyond the component and the policy (DOCTRINE D-08, DR-5).

    Inputs only, so a re-run can tell it may reuse a decision before calling the model. A field the
    review starts reading must be added here; a canary removes the card digest and the suite goes red.
    """
    canonical = json.dumps(
        {"card_sha256": _sha256(card), "prompt_sha256": prompt_sha256, "model": model, "effort": effort},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_digest(card: str, extraction: Extraction) -> str:
    """The model's extraction and the card it was read from, recorded on the decision as evidence."""
    canonical = json.dumps(
        {
            "card_sha256": _sha256(card),
            "license_id": extraction.license_id,
            "quote": extraction.quote,
            "restrictions": [[r.text, r.quote] for r in extraction.restrictions],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
