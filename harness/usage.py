"""Token usage and cost.

Tokens come from the API response (`usage`), so they are measured, not
estimated. Cost is derived from a price table that carries its source and the
date it was checked; a model with no price returns `None`, never 0.0, so a
missing price can't pass for a free run.

Cost is computed per call (`call_cost`) and summed: a price tier depends on the
size of one prompt, and one call the table does not cover makes the whole run
unpriced. Every way the table could under-price a call gives `None`: an unknown
model, a prompt above the tier the table covers, a cache write whose 5-minute /
1-hour split is unknown, or an inference region other than the one priced.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from harness.storage import JSONObject

# USD per million tokens. Fill only from the provider's current pricing page and
# update PRICES_CHECKED_ON when you do.
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES_CHECKED_ON = "2026-10-09"
PRICED_REGION = "global"  # `inference_geo: us` is priced x1.1; it is not in this table


@dataclass(frozen=True)
class Price:
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float
    max_prompt_tokens: int | None = None  # above this, another tier applies that the table does not hold


PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(10.0, 12.5, 20.0, 0.25, 50.0),
    "claude-opus-5-5": Price(4.0, 5.0, 8.0, 0.20, 20.0),
    "claude-sonnet-5-5": Price(2.0, 2.5, 4.0, 0.10, 10.0),
    "claude-haiku-5-5": Price(0.10, 0.125, 0.20, 0.01, 0.50, max_prompt_tokens=100_000),
    # Other providers through OpenRouter (KeysBench configuration B). Source: the `pricing` of each model in
    # OPENROUTER_PRICES_SOURCE, checked on OPENROUTER_PRICES_CHECKED_ON. A cache write OpenRouter does not
    # list is priced as plain input; the higher tier above max_prompt_tokens is not in the table.
    "openai/gpt-5.6-sol": Price(2.0, 2.5, 2.5, 0.2, 10.0, max_prompt_tokens=272_000),
    "google/gemini-3.1-pro-preview": Price(2.0, 0.375, 0.375, 0.2, 12.0, max_prompt_tokens=200_000),
    "qwen/qwen3-coder-next": Price(0.12, 0.12, 0.12, 0.07, 0.80),
}
OPENROUTER_PRICES_SOURCE = "https://openrouter.ai/api/v1/models"
OPENROUTER_PRICES_CHECKED_ON = "2026-10-11"


@dataclass
class Usage:
    # The API splits input into three counters: uncached tokens, tokens written
    # to the prompt cache, and tokens read from it. Total input is their sum;
    # summing only `input_tokens` undercounts as soon as caching is on.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # Nested in the API's `usage`: the cache writes by TTL (priced differently) and the
    # thinking part of `output_tokens` (already included in it; kept to report it).
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    thinking_tokens: int = 0

    def add(self, raw: JSONObject | None) -> None:
        raw = raw or {}
        for f in fields(self)[:4]:  # the flat counters: the field names are the API's usage keys
            setattr(self, f.name, getattr(self, f.name) + int(raw.get(f.name) or 0))
        split = raw.get("cache_creation") or {}
        self.cache_write_5m += int(split.get("ephemeral_5m_input_tokens") or 0)
        self.cache_write_1h += int(split.get("ephemeral_1h_input_tokens") or 0)
        self.thinking_tokens += int((raw.get("output_tokens_details") or {}).get("thinking_tokens") or 0)

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


def _priced(u: Usage, price: Price) -> float | None:
    if u.cache_creation_input_tokens != u.cache_write_5m + u.cache_write_1h:
        # Cache writes are priced by TTL; without the split there is no honest cost.
        return None
    return (
        u.input_tokens * price.input
        + u.cache_write_5m * price.cache_write_5m
        + u.cache_write_1h * price.cache_write_1h
        + u.cache_read_input_tokens * price.cache_read
        + u.output_tokens * price.output
    ) / 1_000_000


def call_cost(raw: JSONObject | None, model: str) -> float | None:
    """The cost of one call from its own `usage`, or `None` when the table does not cover it."""
    price = PRICES.get(model)
    if price is None or not raw or raw.get("inference_geo") != PRICED_REGION:
        return None
    u = Usage()
    u.add(raw)
    if price.max_prompt_tokens is not None and u.total_input_tokens > price.max_prompt_tokens:
        return None
    return _priced(u, price)


def cost_usd(usage: Usage, model: str) -> float | None:
    """The cost of an aggregate. Tiers and regions are per call: use `call_cost` per call when you can."""
    price = PRICES.get(model)
    if price is None:
        return None
    return _priced(usage, price)
