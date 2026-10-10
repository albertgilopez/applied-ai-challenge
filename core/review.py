"""The human side of a review: which recorded decision is "the same", who said what, which line wins.

The ledger holds three kinds of line (STORY-003 DR-1): a `decision` made by `decide()`, and the
reviewer lines `approve` and `override`, each pointing at a decision id. Nothing is edited: `fold`
replays the lines in file order into one `ReviewState` per decision, and the latest reviewer line on
a decision gives its final verdict (DR-3). Lines of other kinds (model calls, tool calls) are ignored,
so the review can share one ledger with the agent.

Pure: the caller reads and appends the ledger; this module only interprets lines and refuses bad
ones before they are written (DR-2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from core.component import Component, JSONObject
from core.decide import Decision
from core.policy import ALLOW, REJECT, REVIEW

VERDICTS = (ALLOW, REVIEW, REJECT)


class ReviewError(ValueError):
    pass


def decision_key(component: Component, policy_sha256: str, card_key: str | None = None) -> str:
    """When a recorded decision may be reused: every input `decide()` reads, plus the policy.

    Identity alone was not enough (security review C12): two packages with the same name and version
    but different licenses would share one verdict, and a policy edit would be ignored on a re-run.
    A field added to `decide()` must be added here too (DOCTRINE D-08). An AI model reviewed against
    its card adds `card_key` (STORY-002 DR-5); every other decision keeps the key it had.
    """
    fields: JSONObject = {
        "identity": component.identity,
        "license_expression": component.license_expression,
        "source_url": component.source_url,
        "policy_sha256": policy_sha256,
    }
    if card_key is not None:
        fields["card_key"] = card_key
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decision_record(
    component: Component,
    decision: Decision,
    policy_sha256: str,
    card_key: str | None = None,
    evidence: JSONObject | None = None,
) -> JSONObject:
    record: JSONObject = {
        "kind": "decision",
        "key": decision_key(component, policy_sha256, card_key),
        "identity": component.identity,
        "name": component.name,
        "version": component.version,
        "verdict": decision.verdict,
        "reason": decision.reason,
        "source_url": decision.source_url,
        "policy_sha256": policy_sha256,
    }
    if evidence is not None:
        record["model_card"] = evidence
    return record


@dataclass(frozen=True)
class Review:
    kind: str  # "approve" | "override"
    by: str
    reason: str | None
    verdict: str  # an approval records the verdict it approved
    at: str


@dataclass(frozen=True)
class ReviewState:
    decision_id: str
    key: str
    identity: str
    name: str
    version: str | None
    decided_verdict: str
    reason: str
    source_url: str | None
    reviews: tuple[Review, ...] = ()

    @property
    def final_verdict(self) -> str:
        return self.reviews[-1].verdict if self.reviews else self.decided_verdict

    @property
    def status(self) -> str:
        if not self.reviews:
            return "pending"
        return "approved" if self.reviews[-1].kind == "approve" else "overridden"


def fold(records: Iterable[JSONObject]) -> dict[str, ReviewState]:
    """Decision id -> its state after every reviewer line, replayed in file order."""
    states: dict[str, ReviewState] = {}
    for r in records:
        kind = r.get("kind")
        if kind == "decision":
            states[r["id"]] = ReviewState(
                decision_id=r["id"],
                key=r["key"],
                identity=r["identity"],
                name=r["name"],
                version=r.get("version"),
                decided_verdict=r["verdict"],
                reason=r["reason"],
                source_url=r.get("source_url"),
            )
        elif kind in ("approve", "override"):
            target = states.get(r.get("decision", ""))
            if target is None:
                # Only a hand-edited ledger gets here: check_* refuse it before writing.
                raise ReviewError(f"line {r.get('id')}: {kind} points at {r.get('decision')!r}, which is no decision")
            verdict = target.final_verdict if kind == "approve" else r["verdict"]
            review = Review(kind, r["by"], r.get("reason"), verdict, r.get("at", ""))
            states[target.decision_id] = _with_review(target, review)
    return states


def _with_review(state: ReviewState, review: Review) -> ReviewState:
    return ReviewState(**{**state.__dict__, "reviews": (*state.reviews, review)})


def _required(value: str | None, what: str) -> str:
    if value is None or not value.strip():
        raise ReviewError(f"{what} is required")
    return value.strip()


def _existing(states: dict[str, ReviewState], decision_id: str) -> None:
    if decision_id not in states:
        raise ReviewError(f"{decision_id!r} is no decision in this ledger")


def check_approve(states: dict[str, ReviewState], decision_id: str, by: str, reason: str | None) -> JSONObject:
    """The `approve` line to append, or ReviewError. Nothing is written on refusal."""
    _existing(states, decision_id)
    record: JSONObject = {"kind": "approve", "decision": decision_id, "by": _required(by, "a reviewer (--by)")}
    record["reason"] = reason.strip() if reason and reason.strip() else None
    return record


def check_override(
    states: dict[str, ReviewState], decision_id: str, verdict: str, by: str, reason: str | None
) -> JSONObject:
    """The `override` line to append, or ReviewError. Nothing is written on refusal."""
    _existing(states, decision_id)
    if verdict not in VERDICTS:
        raise ReviewError(f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
    return {
        "kind": "override",
        "decision": decision_id,
        "verdict": verdict,
        "by": _required(by, "a reviewer (--by)"),
        "reason": _required(reason, "a reason (--reason)"),
    }
