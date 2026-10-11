"""From a component's license expression and the policy to a verdict.

Verdicts are ordered `Reject < Needs review < Allow`. `OR` takes the best branch
(the licensee may choose), `AND` the worst (every term applies). The reason of
the branch that decided is kept, so a `Reject` names the id that rejected it.
Anything missing, unparseable or unlisted is `Needs review` (DR-1).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.component import Component
from core.license_expr import And, Expr, Leaf, NestingError, Or, ParseError, parse
from core.policy import ALLOW, REJECT, REVIEW, Policy

RANK = {REJECT: 0, REVIEW: 1, ALLOW: 2}
SECTION_NAME = {ALLOW: "allowed", REVIEW: "under review", REJECT: "rejected"}


@dataclass(frozen=True)
class Decision:
    ref: str
    verdict: str
    reason: str
    source_url: str | None


def _leaf(leaf: Leaf, policy: Policy) -> tuple[str, str]:
    verdict = policy.lookup(leaf.text)
    if verdict is not None:
        return verdict, f"{leaf.text} is {SECTION_NAME[verdict]} by policy"
    if "LicenseRef-" in leaf.id:
        return REVIEW, f"custom license {leaf.text} not in policy"
    return REVIEW, f"{leaf.text} not in policy"


def evaluate(node: Expr, policy: Policy) -> tuple[str, str]:
    if isinstance(node, Leaf):
        return _leaf(node, policy)
    results = [evaluate(item, policy) for item in node.items]
    if isinstance(node, Or):
        return max(results, key=lambda r: RANK[r[0]])
    if isinstance(node, And):
        return min(results, key=lambda r: RANK[r[0]])
    raise TypeError(f"unknown node {node!r}")  # pragma: no cover


def decide(component: Component, policy: Policy) -> Decision:
    expression = (component.license_expression or "").strip()
    if not expression:
        verdict, reason = REVIEW, "no license declared"
    else:
        try:
            verdict, reason = evaluate(parse(expression), policy)
        except NestingError as exc:
            verdict, reason = REVIEW, f"{exc}; not decided"
        except ParseError as exc:
            verdict, reason = REVIEW, f"{exc} in {expression!r}"
    if not component.source_url:
        reason += "; no source declared"
    return Decision(component.ref, verdict, reason, component.source_url)
