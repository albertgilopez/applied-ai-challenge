"""T2: license policy (STORY-001 DR-4, DR-8)."""

import pytest

from core.policy import Policy, PolicyError
from tests.story_001.cases import CASES

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


@pytest.mark.parametrize("row", CASES["S1-26"]["rows"], ids=["scalar-section", "nested-entry"])
def test_a_section_must_be_a_list_and_errors_name_the_position(row):  # S1-26, security scan C8
    with pytest.raises(PolicyError, match=row["message_contains"].replace("[", r"\[").replace("]", r"\]")):
        Policy.from_dict(row["policy"])


def test_a_bad_entry_is_not_echoed_in_the_error():  # security scan C6: the repr itself was the bomb
    huge = ["x"] * 100_000
    with pytest.raises(PolicyError) as err:
        Policy.from_dict({"allowed": ["MIT", huge]})
    assert len(str(err.value)) < 200


def test_mixed_type_section_names_are_a_policy_error():  # security scan C15
    with pytest.raises(PolicyError, match="unknown section"):
        Policy.from_dict({"allowed": ["MIT"], True: ["x"]})


def test_a_lookalike_that_lower_folds_to_ascii_is_not_matched():  # S1-24, security scan C9
    # str.lower() maps the Kelvin sign (U+212A) to an ASCII "k": without the ASCII guard,
    # "BlueOa<KELVIN>-1.0.0" would read as the allowed "BlueOak-1.0.0".
    p = Policy.from_dict({"allowed": ["BlueOak-1.0.0"]})
    lookalike = "BlueOa" + chr(0x212A) + "-1.0.0"
    assert lookalike.lower() == "blueoak-1.0.0"  # the premise: lower() alone would match
    assert p.lookup(lookalike) is None
