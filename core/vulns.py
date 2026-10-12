"""From a license decision and the component's OSV vulnerabilities to the final verdict (STORY-005).

A critical vulnerability rejects the component, whatever its license says. Fail closed (D-02): a
component that was not checked, or a vulnerability whose severity is unknown, is never `Allow`.
The adapter that queries OSV lives outside `core/`; this rule only reads what it was given.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.decide import RANK, Decision
from core.policy import ALLOW, REJECT, REVIEW


def apply_vulnerabilities(decision: Decision, vulns: list[dict[str, Any]] | None) -> Decision:
    if vulns is None:
        verdict = REVIEW if decision.verdict == ALLOW else decision.verdict
        return replace(decision, verdict=verdict, reason=decision.reason + "; not checked against OSV")
    verdict = decision.verdict
    notes: list[str] = []
    for v in vulns:
        severity = (v.get("severity") or "").upper()
        if severity == "CRITICAL":
            verdict, notes = REJECT, [*notes, f"{v['id']} is critical"]
        elif not severity:
            verdict = min(verdict, REVIEW, key=RANK.__getitem__)
            notes.append(f"{v['id']} has unknown severity")
        else:
            notes.append(f"{v['id']} ({severity.lower()})")
    if not notes:
        return decision
    return replace(decision, verdict=verdict, reason=decision.reason + "; OSV: " + ", ".join(notes))
