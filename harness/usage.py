"""Token usage and cost.

Tokens come from the API response (`usage`), so they are measured, not
estimated. Cost is derived from a price table that carries its source and the
date it was checked; a model with no price returns `None`, never 0.0, so a
missing price can't pass for a free run.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from harness.storage import JSONObject

# USD per million tokens (input, output). Fill only from the provider's current
# pricing page and update PRICES_CHECKED_ON when you do.
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES_CHECKED_ON = None  # set when the table is verified
PRICES: dict[str, tuple[float, float]] = {}


@dataclass
class Usage:
    # The API splits input into three counters: uncached tokens, tokens written
    # to the prompt cache, and tokens read from it. Total input is their sum;
    # summing only `input_tokens` undercounts as soon as caching is on.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, raw: JSONObject | None) -> None:
        raw = raw or {}
        for f in fields(self):  # the field names are the API's usage keys
            setattr(self, f.name, getattr(self, f.name) + int(raw.get(f.name) or 0))

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


def cost_usd(usage: Usage, model: str) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    if usage.cache_creation_input_tokens or usage.cache_read_input_tokens:
        # Cache writes and reads are priced differently from plain input; until
        # those rates are in the table, a cached run has no honest cost.
        return None
    per_in, per_out = price
    return (usage.input_tokens * per_in + usage.output_tokens * per_out) / 1_000_000
