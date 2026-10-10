"""STORY-002: the reviewer drives the harness and returns the model's answer as typed data.

The model is scripted. What is under test: the card is read through the tool by id, the answer is
validated by code, the prompt is governed, and the run's usage, cost and latency are recorded (S2-07).
"""

import json
from pathlib import Path

import pytest

from agent.reviewer import PROMPT, PROMPT_ID, review_card
from core.model_card import Extraction
from harness.ledger import Ledger
from harness.prompts import PromptRegistry, UnapprovedPrompt

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "samples" / "model-cards"
USAGE = {"input_tokens": 900, "output_tokens": 80, "inference_geo": "global"}
OK = {"license_id": "apache-2.0", "quote": "license: apache-2.0", "restrictions": []}
NONE = {"license_id": None, "quote": None, "restrictions": []}


class Scripted:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


def read_card(model_id):
    call = {"type": "tool_use", "id": "t1", "name": "read_model_card", "input": {"model_id": model_id}}
    return {"stop_reason": "tool_use", "content": [call], "usage": USAGE}


def answer(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}], "usage": USAGE}


@pytest.fixture
def registry(tmp_path):
    r = PromptRegistry(tmp_path / "approvals.jsonl")
    r.approve(PROMPT_ID, PROMPT, by="test", validation_ref="tests/story_002")
    return r


def run(tmp_path, registry, responses, model_id="mistralai/Mistral-7B-v0.1"):
    provider = Scripted(responses)
    ledger = Ledger(tmp_path / "l.jsonl")
    result = review_card(model_id, provider=provider, ledger=ledger, cards_dir=CARDS, registry=registry)
    return result, provider


def test_the_card_is_read_through_the_tool_and_the_answer_becomes_typed_data(tmp_path, registry):
    result, provider = run(tmp_path, registry, [read_card("mistralai/Mistral-7B-v0.1"), answer(OK)])
    assert result.extraction == Extraction("apache-2.0", "license: apache-2.0", ())
    tool_result = provider.requests[1]["messages"][-1]["content"][0]
    assert "license: apache-2.0" in tool_result["content"]
    assert provider.requests[0]["output_config"]["effort"] == "medium"
    assert provider.requests[0]["output_config"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    "bad",
    ["not json", "[]", {"license_id": 3, "quote": None, "restrictions": []}, {"license_id": None, "quote": None}],
    ids=["text", "list", "wrong-type", "missing-field"],
)
def test_an_answer_that_does_not_fit_the_schema_is_no_extraction(tmp_path, registry, bad):
    result, _ = run(tmp_path, registry, [answer(bad)])
    assert result.extraction is None


def test_a_url_given_to_the_tool_is_refused_and_the_model_sees_the_refusal(tmp_path, registry):
    _, provider = run(tmp_path, registry, [read_card("https://evil.example/x"), answer(NONE)])
    tool_result = provider.requests[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"]
    assert "not a model id" in tool_result["content"]


def test_s2_07_usage_cost_and_latency_are_recorded(tmp_path, registry):
    run(tmp_path, registry, [read_card("mistralai/Mistral-7B-v0.1"), answer(OK)])
    end = next(r for r in Ledger(tmp_path / "l.jsonl").read() if r["kind"] == "run_end")
    assert (end["input_tokens"], end["output_tokens"]) == (1800, 160)
    assert end["cost_usd"] == pytest.approx(2 * (900 * 0.10 + 80 * 0.50) / 1_000_000)
    assert end["latency_s"] >= 0


def test_the_prompt_is_governed(tmp_path):
    with pytest.raises(UnapprovedPrompt):
        review_card(
            "mistralai/Mistral-7B-v0.1",
            provider=Scripted([]),
            ledger=Ledger(tmp_path / "l.jsonl"),
            cards_dir=CARDS,
            registry=PromptRegistry(tmp_path / "none.jsonl"),
        )


def test_the_prompt_shipped_in_the_repo_is_approved():
    assert PromptRegistry(ROOT / "agent" / "prompts" / "approved.jsonl").is_approved(PROMPT_ID, PROMPT)
