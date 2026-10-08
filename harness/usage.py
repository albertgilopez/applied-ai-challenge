"""Token usage and cost.

Tokens come from the API response (`usage`), so they are measured, not
estimated. Cost is derived from a price table that carries its source and the
date it was checked; a model with no price returns `None`, never 0.0, so a
missing price can't pass for a free run.
"""
from __future__ import annotations

from dataclasses import dataclass

# USD per million tokens (input, output). Fill only from the provider's current
# pricing page and update PRICES_CHECKED_ON when you do.
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES_CHECKED_ON = None  # set when the table is verified
PRICES: dict[str, tuple[float, float]] = {}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, raw: dict | None) -> None:
        raw = raw or {}
        self.input_tokens += int(raw.get("input_tokens") or 0)
        self.output_tokens += int(raw.get("output_tokens") or 0)


def cost_usd(usage: Usage, model: str) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    per_in, per_out = price
    return (usage.input_tokens * per_in + usage.output_tokens * per_out) / 1_000_000
