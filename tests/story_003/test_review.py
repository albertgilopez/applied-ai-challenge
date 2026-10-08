"""STORY-003 review rules on in-memory ledger lines: the decision key, the fold, the refusals."""

import itertools

import pytest

from core.component import Component
from core.decide import decide
from core.policy import Policy
from core.review import ReviewError, check_approve, check_override, decision_key, decision_record, fold
from tests.story_001.cases import load_cases

# ── T2: the policy digest (DR-4, DR-5) ──────────────────────────────────────

BASE = {"allowed": ["MIT", "Apache-2.0"], "review": ["LGPL-2.1-only"], "rejected": ["GPL-3.0-only"]}


def test_policy_digest_ignores_order_and_case():  # S3-09
    reordered = {"rejected": ["gpl-3.0-only"], "allowed": ["Apache-2.0", "mit"], "review": ["LGPL-2.1-only"]}
    assert Policy.from_dict(BASE).digest() == Policy.from_dict(reordered).digest()


def test_policy_digest_changes_when_an_id_moves_section():  # S3-09
    moved = {"allowed": ["MIT", "Apache-2.0"], "review": [], "rejected": ["GPL-3.0-only", "LGPL-2.1-only"]}
    assert Policy.from_dict(BASE).digest() != Policy.from_dict(moved).digest()


def test_policy_digest_is_a_sha256_hex():  # S3-09
    d = Policy.from_dict(BASE).digest()
    assert len(d) == 64 and int(d, 16) >= 0


# ── T3: decision key, fold, refusals (DR-1..DR-5) ───────────────────────────

CASES = load_cases("STORY-003")
POLICY = Policy.from_dict(BASE)
_ids = itertools.count()


def comp(name="libfoo", version="1.0", license="LGPL-2.1-only", source="https://github.com/o/libfoo"):
    return Component(name, name, version, "library", None, license, source)


def line(record):
    """What the ledger adds to every record."""
    return {"id": f"L{next(_ids)}", "at": "2026-10-09T00:00:00Z", **record}


def scanned(*components, policy=POLICY):
    return [line(decision_record(c, decide(c, policy), policy.digest())) for c in components]


def test_the_key_changes_with_every_input_of_decide():  # S3-08, S3-09, DR-4
    base = comp()
    d = POLICY.digest()
    assert decision_key(base, d) == decision_key(comp(), d)
    assert decision_key(base, d) != decision_key(comp(license="MIT"), d)
    assert decision_key(base, d) != decision_key(comp(source=None), d)
    assert decision_key(base, d) != decision_key(comp(version="1.1"), d)
    assert decision_key(base, d) != decision_key(base, "0" * 64)


def test_same_identity_different_license_are_separate_decisions():  # S3-08
    ledger = scanned(
        comp(name="twin", version="2.0", license="MIT"), comp(name="twin", version="2.0", license="GPL-3.0-only")
    )
    states = fold(ledger)
    assert sorted(s.final_verdict for s in states.values()) == ["Allow", "Reject"]
    mit = next(s for s in states.values() if s.decided_verdict == "Allow")
    ledger.append(line(check_override(states, mit.decision_id, "Allow", "Ana Legal", "approved MIT copy")))
    gpl = next(s for s in fold(ledger).values() if s.decided_verdict == "Reject")
    assert gpl.status == "pending"


def test_an_override_is_a_new_line_and_the_decision_stays():  # S3-01
    ledger = scanned(comp())
    original = dict(ledger[0])
    [state] = fold(ledger).values()
    ledger.append(line(check_override(fold(ledger), state.decision_id, "Allow", "Ana Legal", "dynamic linking only")))
    assert [r["kind"] for r in ledger] == ["decision", "override"]
    assert ledger[0] == original
    assert ledger[1]["decision"] == original["id"]


@pytest.mark.parametrize("row", CASES["S3-02"]["rows"], ids=["empty-by", "blank-by", "empty-reason", "no-reason"])
def test_an_override_needs_a_reviewer_and_a_reason(row):  # S3-02
    states = fold(scanned(comp()))
    [decision_id] = states
    o = row["override"]
    with pytest.raises(ReviewError):
        check_override(states, decision_id, o["verdict"], o.get("by", ""), o.get("reason", ""))


def test_the_latest_reviewer_line_wins_and_all_are_listed():  # S3-03
    ledger = scanned(comp())
    [decision_id] = fold(ledger)
    for step in CASES["S3-03"]["steps"]:
        o = step["override"]
        ledger.append(line(check_override(fold(ledger), decision_id, o["verdict"], o["by"], o["reason"])))
    state = fold(ledger)[decision_id]
    expected = CASES["S3-03"]["expected"]
    assert (state.final_verdict, state.decided_verdict, state.status) == (
        expected["final_verdict"],
        expected["decided_verdict"],
        expected["status"],
    )
    assert [(r.by, r.verdict) for r in state.reviews] == [(e["by"], e["verdict"]) for e in expected["reviews_listed"]]


def test_unknown_decision_or_verdict_is_refused():  # S3-06
    states = fold(scanned(comp()))
    [decision_id] = states
    with pytest.raises(ReviewError, match="no decision"):
        check_override(states, "does-not-exist", "Allow", "Ana Legal", "ok")
    with pytest.raises(ReviewError, match="verdict"):
        check_override(states, decision_id, "Allowed", "Ana Legal", "ok")
    with pytest.raises(ReviewError, match="no decision"):
        check_approve(states, "does-not-exist", "Ana Legal", None)


def test_approve_needs_a_reviewer_and_clears_pending():  # S3-07
    ledger = scanned(comp())
    [decision_id] = fold(ledger)
    with pytest.raises(ReviewError):
        check_approve(fold(ledger), decision_id, "  ", None)
    ledger.append(line(check_approve(fold(ledger), decision_id, "Ana Legal", None)))
    state = fold(ledger)[decision_id]
    assert (state.status, state.final_verdict) == ("approved", "Needs review")


def test_a_reviewer_line_for_an_unknown_decision_is_corruption():  # DR-1
    ledger = scanned(comp()) + [
        line({"kind": "override", "decision": "ghost", "verdict": "Allow", "by": "x", "reason": "y"})
    ]
    with pytest.raises(ReviewError, match="ghost"):
        fold(ledger)


def test_fold_ignores_kinds_it_does_not_know():  # DR-1, model calls share the ledger
    ledger = scanned(comp()) + [line({"kind": "tool_intent", "tool": "card"})]
    assert len(fold(ledger)) == 1
