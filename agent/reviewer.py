"""The model-card reviewer: one governed prompt, one read tool, a structured answer (STORY-002).

The model reads the card and returns what it found; it decides nothing. The answer is validated here
and handed to `core/model_card.py` as typed data, which grounds it against the card and applies the
policy. Every call goes through the harness: the gate, the ledger, usage and record/replay.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.model_cards import MAX_CARD_BYTES, load_card
from core.model_card import Extraction, Restriction
from harness.catalog import Catalog, tool
from harness.gate import Gate
from harness.ledger import Ledger
from harness.loop import Agent, RunResult
from harness.prompts import PromptRegistry
from harness.providers import Provider

HERE = Path(__file__).resolve().parent
PROMPT_ID = "model-card-reviewer"
PROMPT = (HERE / "prompts" / "model_card.md").read_text(encoding="utf-8")
APPROVALS = HERE / "prompts" / "approved.jsonl"
MODEL = "claude-haiku-5-5"
EFFORT = "medium"

_NULLABLE_STRING: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "license_id": _NULLABLE_STRING,
        "quote": _NULLABLE_STRING,
        "restrictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["text", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["license_id", "quote", "restrictions"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CardResult:
    extraction: Extraction | None  # None: the answer could not be read as the schema says
    run: RunResult


def _as_extraction(text: str) -> Extraction | None:
    """Validate the answer here even though the schema was sent: what the code relies on, the code checks."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not {"license_id", "quote", "restrictions"} <= data.keys():
        return None
    lic, quote, rs = data["license_id"], data["quote"], data["restrictions"]
    if not (lic is None or isinstance(lic, str)) or not (quote is None or isinstance(quote, str)):
        return None
    if not isinstance(rs, list) or not all(
        isinstance(r, dict) and isinstance(r.get("text"), str) and isinstance(r.get("quote"), str) for r in rs
    ):
        return None
    return Extraction(lic or None, quote or None, tuple(Restriction(r["text"], r["quote"]) for r in rs))


def review_card(
    model_id: str,
    *,
    provider: Provider,
    ledger: Ledger,
    cards_dir: Path | str,
    fetch: Callable[[str], str] | None = None,
    env: str = "prod",
    registry: PromptRegistry | None = None,
) -> CardResult:
    catalog = Catalog()

    @tool(catalog, effect="read", path_args=(), description="Read the model card of a model id (org/name).")
    def read_model_card(model_id: str) -> str:
        return load_card(model_id, cards_dir, fetch)[:MAX_CARD_BYTES]

    agent = Agent(
        provider=provider,
        model=MODEL,
        system=PROMPT,
        prompt_id=PROMPT_ID,
        registry=registry or PromptRegistry(APPROVALS),
        catalog=catalog,
        gate=Gate(),
        ledger=ledger,
        env=env,
        max_steps=4,
        max_tokens=4000,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
    )
    run = agent.run(f"Model id: {model_id}")
    return CardResult(_as_extraction(run.text), run)
