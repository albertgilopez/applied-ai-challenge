"""Hidden tests for KB-01: the test the real fix added (deep nesting), plus the behaviour around it.

The contestant's code runs in its own process through `kbcall`; only plain JSON comes back.
"""

from kbcall import call

POLICY = "{'allowed': ['MIT', 'Apache-2.0'], 'rejected': ['GPL-3.0-only']}"
MODULES = ("core.decide", "core.component", "core.policy")


def decide(expression: str) -> list:
    return call(
        "(lambda d: [d.verdict, d.reason])(core.decide.decide("
        f"core.component.Component('ref', 'name', '1.0', 'library', None, {expression!r}, 'https://example.com/x'),"
        f" core.policy.Policy.from_dict({POLICY})))",
        *MODULES,
        timeout_s=60,
    )


def test_deep_nesting_is_needs_review():
    verdict, reason = decide("(" * 260 + "MIT" + ")" * 260)
    assert verdict == "Needs review"
    assert "nested too deeply" in reason


def test_nesting_of_64_is_still_decided():
    assert decide("(" * 64 + "MIT" + ")" * 64)[0] == "Allow"


def test_or_takes_the_best_branch():
    assert decide("MIT OR GPL-3.0-only")[0] == "Allow"


def test_and_takes_the_worst_branch():
    assert decide("MIT AND GPL-3.0-only")[0] == "Reject"


def test_nested_mix_is_decided():
    assert decide("(MIT AND (Apache-2.0 OR GPL-3.0-only))")[0] == "Allow"


def test_a_broken_expression_is_needs_review():
    assert decide("MIT AND")[0] == "Needs review"
