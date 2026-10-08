"""STORY-003 review rules on in-memory ledger lines: the decision key, the fold, the refusals."""

from core.policy import Policy

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
