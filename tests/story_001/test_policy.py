"""T2: license policy (STORY-001 DR-4, DR-8)."""
import pytest

from core.policy import Policy, PolicyError

POLICY = {
    "allowed": ["MIT", "Apache-2.0", "GPL-2.0-only WITH Classpath-exception-2.0"],
    "review": ["LGPL-2.1-only"],
    "rejected": ["GPL-3.0-only"],
}


def test_lookup_is_case_insensitive():  # S1-11
    p = Policy.from_dict(POLICY)
    assert p.lookup("mit") == "Allow"
    assert p.lookup("gpl-3.0-ONLY") == "Reject"
    assert p.lookup("LGPL-2.1-only") == "Needs review"


def test_an_unlisted_id_is_not_guessed():  # DR-4
    p = Policy.from_dict(POLICY)
    assert p.lookup("Apache-2.0+") is None
    assert p.lookup("GPL-2.0-only WITH LLVM-exception") is None
    assert p.lookup("GPL-2.0-only WITH Classpath-exception-2.0") == "Allow"


def test_the_same_id_in_two_lists_is_refused():  # S1-19
    with pytest.raises(PolicyError, match="'mit'.*allowed.*rejected"):
        Policy.from_dict({"allowed": ["MIT"], "rejected": ["mit"]})


@pytest.mark.parametrize("entry", [False, None, 3])
def test_a_non_string_entry_is_refused(entry):  # YAML 1.1 reads `- no` as False
    with pytest.raises(PolicyError, match="not a license id"):
        Policy.from_dict({"allowed": ["MIT", entry]})


def test_an_unknown_section_is_refused():
    with pytest.raises(PolicyError, match="unknown section"):
        Policy.from_dict({"allowed": ["MIT"], "allow": ["Apache-2.0"]})


def test_an_empty_policy_is_refused():
    with pytest.raises(PolicyError, match="empty"):
        Policy.from_dict({})
