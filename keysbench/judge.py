"""The judge (STORY-004 DR-8): a model only where a test cannot see, its evidence checked by code.

Only KB-06 uses it: whether a code review found a planted defect is not something a test can run. The
judge reads the contestant's review as data (between delimiters, model names masked, its prompt
approved by hash), and returns a verdict and the sentence of the review it rests on. Code then checks
that sentence is in the review and points at the planted line; if not, the verdict is `fail`, whatever
the judge said. The verdict is frozen on the attempt line with the digests of the prompt, the rubric
and the review: scoring reads it and never asks again.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from harness.catalog import Catalog
from harness.gate import Gate
from harness.ledger import Ledger
from harness.loop import Agent
from harness.prompts import PromptRegistry, digest
from harness.providers import Provider

HERE = Path(__file__).resolve().parent
PROMPT_ID = "keysbench-judge"
PROMPT = (HERE / "prompts" / "judge.md").read_text("utf-8")
RUBRIC_PATH = HERE / "rubrics" / "kb06.toml"
APPROVALS = HERE / "prompts" / "approved.jsonl"
EFFORT = "high"
MAX_TOKENS = 8000

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "defect_found": {"type": "boolean"},
        "review_quote": {"type": "string"},
    },
    "required": ["verdict", "defect_found", "review_quote"],
    "additionalProperties": False,
}

# Model ids and product names: masked so the judge cannot favour a family it recognises.
_MODEL_NAMES = re.compile(r"claude-[a-z0-9.-]+|Claude\s+(?:Fable|Opus|Sonnet|Haiku)(?:\s+\d+(?:\.\d+)?)?", re.I)


def prompt_digest() -> str:
    return digest(PROMPT)


def rubric_text() -> str:
    return RUBRIC_PATH.read_text("utf-8")


def judge_model_for(contestant_model: str, cfg: dict[str, str]) -> str:
    """The judge is never the contestant's model (DR-8)."""
    default = cfg.get("default", "claude-opus-5-5")
    return cfg.get("instead", "claude-sonnet-5-5") if contestant_model == default else default


def _normalise(text: str) -> str:
    return " ".join(text.split())


def mask(text: str) -> str:
    return _MODEL_NAMES.sub("<contestant>", text)


def _fail(reason: str, **extra: Any) -> dict[str, Any]:
    return {"verdict": "fail", "reason": reason, "review_quote": "", "quote_in_review": False,
            "points_at_defect": False, **extra}  # fmt: skip


def judge_review(
    *,
    review: str,
    diff: str,
    planted_line: str,
    marker: str,
    judge_model: str,
    provider: Provider,
    ledger_path: Path,
    placeholder: str = "",
    registry: PromptRegistry | None = None,
) -> dict[str, Any]:
    base = {
        "model": judge_model,
        "prompt_sha256": prompt_digest(),
        "rubric_sha256": hashlib.sha256(rubric_text().encode("utf-8")).hexdigest(),
        "artifact_sha256": hashlib.sha256(review.encode("utf-8")).hexdigest(),
        "cost_usd": 0.0,
    }
    if not review.strip() or _normalise(review) == _normalise(placeholder):
        return {**_fail("no review written"), **base}
    user = (
        f"Rubric:\n{rubric_text()}\n\nThe change under review:\n```diff\n{diff}```\n\n"
        f"<review>\n{mask(review)}\n</review>"
    )
    agent = Agent(
        provider=provider,
        model=judge_model,
        system=PROMPT,
        prompt_id=PROMPT_ID,
        registry=registry or PromptRegistry(APPROVALS),
        catalog=Catalog(),
        gate=Gate(),
        ledger=Ledger(ledger_path),
        max_steps=1,
        max_tokens=MAX_TOKENS,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
    )
    run = agent.run(user)
    base["cost_usd"] = run.cost_usd
    try:
        answer = json.loads(run.text)
        verdict, found, quote = answer["verdict"], answer["defect_found"], answer["review_quote"]
        if verdict not in ("pass", "fail") or type(found) is not bool or not isinstance(quote, str):
            raise ValueError("shape")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {**_fail("the judge's answer is not the expected JSON"), **base}
    quote_in_review = bool(quote.strip()) and _normalise(quote) in _normalise(mask(review))
    points = _normalise(planted_line) in _normalise(quote) or marker in quote
    result = {
        **base,
        "judge_verdict": verdict,
        "defect_found": found,
        "review_quote": quote,
        "quote_in_review": quote_in_review,
        "points_at_defect": points,
    }
    if verdict != "pass" or not found:
        return {**result, "verdict": "fail", "reason": "the judge did not find the defect in the review"}
    if not quote_in_review:
        return {**result, "verdict": "fail", "reason": "quote not in review"}
    if not points:
        return {**result, "verdict": "fail", "reason": "quote does not point at the planted line"}
    return {**result, "verdict": "pass", "reason": "grounded"}
