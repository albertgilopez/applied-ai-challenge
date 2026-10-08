"""Harness contract tests. They run offline: the model is a scripted fake.

Each test names the property it protects, because these are the properties a
reviewer will ask about: what the agent may do, who approved its prompt, and
whether every step left a record.
"""
import json

import pytest

from harness.catalog import Catalog, tool
from harness.gate import Gate
from harness.ledger import Ledger
from harness.loop import Agent
from harness.prompts import PromptRegistry, UnapprovedPrompt
from harness.replay import CassetteMiss, RecordingProvider, ReplayProvider
from harness.usage import Usage, cost_usd


# ── scripted model ──────────────────────────────────────────────────────────

class ScriptedProvider:
    """Returns pre-written responses in order and keeps every request it saw."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


def tool_use(name, input, id="t1"):
    return {
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": id, "name": name, "input": input}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


def final(text="done"):
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }


@pytest.fixture
def setup(tmp_path):
    catalog = Catalog()

    @tool(catalog, effect="read", description="Read a value")
    def read_value(key: str) -> str:
        return f"value-of-{key}"

    @tool(catalog, effect="outward", description="Send something outside")
    def notify(message: str) -> str:  # pragma: no cover - must never run
        raise AssertionError("an outward tool ran without a human")

    registry = PromptRegistry(tmp_path / "approved.json")
    registry.approve("sys", "be careful", by="reviewer", validation_ref="tests")
    ledger = Ledger(tmp_path / "ledger.jsonl")
    return catalog, registry, ledger, tmp_path


def make_agent(setup, provider, **kw):
    catalog, registry, ledger, tmp = setup
    return Agent(
        provider=provider, model="claude-sonnet-5-5", system="be careful",
        prompt_id="sys", registry=registry, catalog=catalog,
        gate=Gate(write_roots=[tmp]), ledger=ledger, **kw,
    )


# ── catalog and gate ────────────────────────────────────────────────────────

def test_tool_schema_is_derived_from_the_signature(setup):
    catalog = setup[0]
    schema = catalog.get("read_value").schema()
    assert schema["input_schema"]["properties"] == {"key": {"type": "string"}}
    assert schema["input_schema"]["required"] == ["key"]


def test_a_tool_outside_the_catalog_never_runs(setup):
    provider = ScriptedProvider([tool_use("rm_rf", {"path": "/"}), final()])
    result = make_agent(setup, provider).run("go")
    assert result.tool_calls[0]["verdict"] == "deny"
    sent_back = provider.requests[1]["messages"][-1]["content"][0]
    assert sent_back["is_error"] is True and "not in the catalog" in sent_back["content"]


def test_an_outward_tool_is_escalated_and_not_executed(setup):
    seen = []
    provider = ScriptedProvider([tool_use("notify", {"message": "hi"}), final()])
    agent = make_agent(setup, provider, on_escalate=lambda name, args, why: seen.append(name) or "declined")
    result = agent.run("go")
    assert seen == ["notify"]
    assert result.tool_calls[0]["verdict"] == "escalate"


def test_a_write_outside_the_allowed_roots_is_denied(tmp_path):
    catalog = Catalog()

    @tool(catalog, effect="write", description="Write a file", path_args=("path",))
    def write_file(path: str, text: str) -> str:
        return "written"

    gate = Gate(write_roots=[tmp_path / "out"])
    inside = gate.decide(catalog.get("write_file"), {"path": str(tmp_path / "out" / "a.txt"), "text": ""})
    escape = gate.decide(catalog.get("write_file"), {"path": str(tmp_path / "out" / ".." / "x.txt"), "text": ""})
    assert inside.verdict == "allow"
    assert escape.verdict == "deny"


# ── governed prompt ─────────────────────────────────────────────────────────

def test_prod_refuses_an_unapproved_prompt(setup):
    catalog, registry, ledger, tmp = setup
    agent = Agent(
        provider=ScriptedProvider([final()]), model="m", system="a different prompt",
        prompt_id="sys", registry=registry, catalog=catalog,
        gate=Gate(write_roots=[tmp]), ledger=ledger, env="prod",
    )
    with pytest.raises(UnapprovedPrompt):
        agent.run("go")


def test_editing_the_prompt_revokes_its_approval(tmp_path):
    registry = PromptRegistry(tmp_path / "approved.json")
    registry.approve("sys", "v1", by="reviewer", validation_ref="eval-1")
    assert registry.is_approved("sys", "v1")
    assert not registry.is_approved("sys", "v1 plus one word")


def test_an_approval_without_evidence_is_refused(tmp_path):
    registry = PromptRegistry(tmp_path / "approved.json")
    with pytest.raises(ValueError):
        registry.approve("sys", "v1", by="reviewer", validation_ref="")


# ── loop, ledger, usage ─────────────────────────────────────────────────────

def test_every_step_lands_in_the_ledger(setup):
    provider = ScriptedProvider([tool_use("read_value", {"key": "k"}), final("ok")])
    result = make_agent(setup, provider).run("go")
    assert result.text == "ok"
    kinds = [e["kind"] for e in setup[2].read()]
    assert kinds == ["run_start", "model_call", "tool", "model_call", "run_end"]


def test_the_ledger_is_append_only(setup):
    ledger = setup[2]
    first = ledger.append({"kind": "decision", "verdict": "Needs review"})
    ledger.append({"kind": "override", "of": first, "verdict": "Allow"})
    rows = ledger.read()
    assert [r["kind"] for r in rows] == ["decision", "override"]
    assert rows[0]["verdict"] == "Needs review"


def test_usage_is_summed_across_calls(setup):
    provider = ScriptedProvider([tool_use("read_value", {"key": "k"}), final()])
    result = make_agent(setup, provider).run("go")
    assert (result.usage.input_tokens, result.usage.output_tokens) == (220, 30)


def test_the_loop_stops_when_it_stops_making_progress(setup):
    same = [tool_use("read_value", {"key": "k"}, id=f"t{i}") for i in range(10)]
    result = make_agent(setup, ScriptedProvider(same), max_steps=10).run("go")
    assert result.stop_reason == "no_progress"


def test_an_unknown_price_is_none_not_zero():
    assert cost_usd(Usage(1000, 1000), "some-model-nobody-priced") is None


# ── replay (the lab) ────────────────────────────────────────────────────────

def test_a_recorded_run_replays_without_the_network(setup, tmp_path):
    live = ScriptedProvider([tool_use("read_value", {"key": "k"}), final("ok")])
    cassette = tmp_path / "cassette.json"
    make_agent(setup, RecordingProvider(live, cassette)).run("go")

    replayed = make_agent(setup, ReplayProvider(cassette)).run("go")
    assert replayed.text == "ok"


def test_replay_refuses_a_request_it_never_saw(tmp_path):
    cassette = tmp_path / "cassette.json"
    cassette.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(CassetteMiss):
        ReplayProvider(cassette).create(model="m", messages=[{"role": "user", "content": "new"}])
