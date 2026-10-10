"""Usage and cost, priced per call from a table checked on a stated date (STORY-002 S2-07, STORY-004 DR-3).

A cost is either computed from measured usage or `None`. Every way the table could under-price a call
(an unknown model, an unpriced tier, a cache write without its split, another region) gives `None`.
"""

import pytest

from harness.usage import PRICES, PRICES_CHECKED_ON, Usage, call_cost, cost_usd


def raw(**kw):
    base = {"input_tokens": 0, "output_tokens": 0, "inference_geo": "global"}
    base.update(kw)
    return base


def test_the_table_says_when_it_was_checked_and_covers_the_current_models():
    assert PRICES_CHECKED_ON == "2026-10-09"
    assert {"claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"} <= set(PRICES)


def test_input_output_and_cache_read_are_priced_separately():
    # S4-02 row 1: 1000 x $2 + 200 x $10 + 500 x $0.10, per million
    assert call_cost(raw(input_tokens=1000, output_tokens=200, cache_read_input_tokens=500), "claude-sonnet-5-5") == (
        pytest.approx(0.00405)
    )


def test_cache_writes_are_priced_by_their_ttl():
    five = {"cache_creation_input_tokens": 1000, "cache_creation": {"ephemeral_5m_input_tokens": 1000}}
    hour = {"cache_creation_input_tokens": 1000, "cache_creation": {"ephemeral_1h_input_tokens": 1000}}
    assert call_cost(raw(**five), "claude-fable-5-1") == pytest.approx(0.0125)
    assert call_cost(raw(**hour), "claude-fable-5-1") == pytest.approx(0.02)


@pytest.mark.parametrize(
    ("model", "usage"),
    [
        ("claude-unknown-9", raw(input_tokens=1000, output_tokens=200)),
        ("claude-haiku-5-5", raw(input_tokens=150_000, output_tokens=200)),  # the >100k tier is not in the table
        ("claude-sonnet-5-5", raw(cache_creation_input_tokens=1000)),  # a cache write without its split
        ("claude-sonnet-5-5", {**raw(input_tokens=1000), "inference_geo": "us"}),  # a region priced differently
        ("claude-sonnet-5-5", {"input_tokens": 1000, "output_tokens": 0}),  # region not reported
    ],
    ids=["unknown-model", "uncovered-tier", "unsplit-cache-write", "other-region", "no-region"],
)
def test_anything_the_table_does_not_cover_is_none_never_zero(model, usage):
    assert call_cost(usage, model) is None


def test_nested_usage_is_read():
    u = Usage()
    u.add(
        raw(
            input_tokens=3,
            output_tokens=9,
            cache_creation_input_tokens=30,
            cache_creation={"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20},
            output_tokens_details={"thinking_tokens": 7},
        )
    )
    assert (u.cache_write_5m, u.cache_write_1h, u.thinking_tokens) == (10, 20, 7)
    assert u.total_input_tokens == 33


def test_the_aggregate_cost_matches_the_sum_of_calls_and_is_none_for_unknown_models():
    calls = [raw(input_tokens=1000, output_tokens=200), raw(input_tokens=500, cache_read_input_tokens=500)]
    u = Usage()
    for c in calls:
        u.add(c)
    expected = sum(call_cost(c, "claude-sonnet-5-5") for c in calls)
    assert cost_usd(u, "claude-sonnet-5-5") == pytest.approx(expected)
    assert cost_usd(u, "claude-unknown-9") is None
