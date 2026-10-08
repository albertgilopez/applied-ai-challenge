"""T1: SPDX license expression parser (STORY-001 DR-2, DR-4)."""

import pytest

from core.license_expr import And, Leaf, Or, ParseError, parse


def test_a_single_id_is_a_leaf():
    assert parse("MIT") == Leaf("MIT")


def test_and_binds_tighter_than_or():  # S1-12
    assert parse("GPL-3.0-only AND MIT OR Apache-2.0") == Or(
        (
            And((Leaf("GPL-3.0-only"), Leaf("MIT"))),
            Leaf("Apache-2.0"),
        )
    )


def test_parentheses_override_precedence():
    assert parse("GPL-3.0-only AND (MIT OR Apache-2.0)") == And(
        (
            Leaf("GPL-3.0-only"),
            Or((Leaf("MIT"), Leaf("Apache-2.0"))),
        )
    )


def test_with_and_plus_stay_inside_the_leaf():  # S1-13, DR-4
    leaf = parse("GPL-2.0-only WITH Classpath-exception-2.0")
    assert leaf == Leaf("GPL-2.0-only", exception="Classpath-exception-2.0")
    assert leaf.text == "GPL-2.0-only WITH Classpath-exception-2.0"
    plus = parse("Apache-2.0+")
    assert plus == Leaf("Apache-2.0", plus=True) and plus.text == "Apache-2.0+"


def test_licenseref_with_documentref_is_one_id():
    assert parse("DocumentRef-x:LicenseRef-acme") == Leaf("DocumentRef-x:LicenseRef-acme")


@pytest.mark.parametrize(
    "bad, where",
    [
        ("MIT AND (Apache-2.0", "missing ')'"),  # S1-08
        ("MIT and Apache-2.0", "operators are uppercase"),  # S1-11
        ("", "empty"),
        ("MIT AND", "after 'AND'"),
        ("(MIT))", "unexpected ')'"),
        ("WITH MIT", "unexpected 'WITH'"),
        ("MIT WITH", "after 'WITH'"),
    ],
)
def test_parse_errors_say_what_went_wrong(bad, where):
    with pytest.raises(ParseError, match="cannot parse") as err:
        parse(bad)
    assert where in str(err.value)
