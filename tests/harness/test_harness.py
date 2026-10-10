"""Harness contract tests. They run offline: the model is a scripted fake.

Each test names the property it protects, because these are the properties a
reviewer will ask about: what the agent may do, who approved its prompt, and
whether every step left a record.
"""

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

    @tool(catalog, effect="read", description="Read a value", path_args=())
    def read_value(key: str) -> str:
        return f"value-of-{key}"

    @tool(catalog, effect="outward", description="Send something outside")
    def notify(message: str) -> str:  # pragma: no cover - must never run
        raise AssertionError("an outward tool ran without a human")

    registry = PromptRegistry(tmp_path / "approvals.jsonl")
    registry.approve("sys", "be careful", by="reviewer", validation_ref="tests")
    ledger = Ledger(tmp_path / "ledger.jsonl")
    return catalog, registry, ledger, tmp_path


def make_agent(setup, provider, system="be careful", **kw):
    catalog, registry, ledger, tmp = setup
    return Agent(
        provider=provider,
        model="claude-sonnet-5-5",
        system=system,
        prompt_id="sys",
        registry=registry,
        catalog=catalog,
        gate=Gate(write_roots=[tmp]),
        ledger=ledger,
        **kw,
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
    agent = make_agent(setup, ScriptedProvider([final()]), system="a different prompt", env="prod")
    with pytest.raises(UnapprovedPrompt):
        agent.run("go")


def test_crlf_does_not_revoke_an_approval(tmp_path):
    registry = PromptRegistry(tmp_path / "approvals.jsonl")
    registry.approve("sys", "line one\nline two", by="reviewer", validation_ref="eval-1")
    assert registry.is_approved("sys", "line one\r\nline two")


def test_editing_the_prompt_revokes_its_approval(tmp_path):
    registry = PromptRegistry(tmp_path / "approvals.jsonl")
    registry.approve("sys", "v1", by="reviewer", validation_ref="eval-1")
    assert registry.is_approved("sys", "v1")
    assert not registry.is_approved("sys", "v1 plus one word")


def test_an_approval_without_evidence_is_refused(tmp_path):
    registry = PromptRegistry(tmp_path / "approvals.jsonl")
    with pytest.raises(ValueError):
        registry.approve("sys", "v1", by="reviewer", validation_ref="")


# ── loop, ledger, usage ─────────────────────────────────────────────────────


def test_every_step_lands_in_the_ledger(setup):
    provider = ScriptedProvider([tool_use("read_value", {"key": "k"}), final("ok")])
    result = make_agent(setup, provider).run("go")
    assert result.text == "ok"
    kinds = [e["kind"] for e in setup[2].read()]
    assert kinds == ["run_start", "model_call", "tool_intent", "tool", "model_call", "run_end"]


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


def test_output_config_is_sent_on_every_call_and_recorded(setup):
    provider = ScriptedProvider([tool_use("read_value", {"key": "k"}), final()])
    config = {"effort": "medium"}
    make_agent(setup, provider, output_config=config).run("go")
    assert [r.get("output_config") for r in provider.requests] == [config, config]
    _, _, ledger, _ = setup
    start = next(r for r in ledger.read() if r["kind"] == "run_start")
    assert start["output_config"] == config


def test_the_run_cost_is_the_sum_of_its_calls_or_none_if_one_is_unpriced(setup):
    priced = {"input_tokens": 1000, "output_tokens": 100, "inference_geo": "global"}
    first, second = tool_use("read_value", {"key": "k"}), final()
    first["usage"], second["usage"] = priced, priced
    result = make_agent(setup, ScriptedProvider([first, second])).run("go")
    assert result.cost_usd == pytest.approx(2 * (1000 * 2 + 100 * 10) / 1_000_000)

    unpriced = final()
    unpriced["usage"] = {"input_tokens": 1000, "output_tokens": 100}  # no region reported
    first = tool_use("read_value", {"key": "k"})
    first["usage"] = priced
    assert make_agent(setup, ScriptedProvider([first, unpriced])).run("go").cost_usd is None


def test_the_loop_stops_when_it_stops_making_progress(setup):
    same = [tool_use("read_value", {"key": "k"}, id=f"t{i}") for i in range(10)]
    result = make_agent(setup, ScriptedProvider(same), max_steps=10).run("go")
    assert result.stop_reason == "no_progress"


def test_cache_tokens_count_as_input():
    u = Usage()
    u.add({"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 1000})
    assert u.total_input_tokens == 1210


def test_a_cached_run_is_not_priced_as_plain_input(monkeypatch):
    import harness.usage as usage

    monkeypatch.setitem(usage.PRICES, "m", usage.Price(1.0, 2.0, 3.0, 0.5, 1.0))
    assert cost_usd(Usage(1_000_000, 0), "m") == 1.0
    # a cache read is priced at its own rate, not as plain input
    assert cost_usd(Usage(0, 0, cache_read_input_tokens=1_000_000), "m") == 0.5
    # a cache write whose 5m/1h split is unknown has no honest price
    assert cost_usd(Usage(0, 0, cache_creation_input_tokens=1000), "m") is None


def test_an_unknown_price_is_none_not_zero():
    assert cost_usd(Usage(1000, 1000), "some-model-nobody-priced") is None


# ── replay (the lab) ────────────────────────────────────────────────────────


def test_a_recorded_run_replays_without_the_network(setup, tmp_path):
    live = ScriptedProvider([tool_use("read_value", {"key": "k"}), final("ok")])
    cassette = tmp_path / "cassette.jsonl"
    make_agent(setup, RecordingProvider(live, cassette)).run("go")

    replayed = make_agent(setup, ReplayProvider(cassette)).run("go")
    assert replayed.text == "ok"


def test_replay_refuses_a_request_it_never_saw(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    cassette.write_text("", encoding="utf-8")
    with pytest.raises(CassetteMiss):
        ReplayProvider(cassette).create(model="m", messages=[{"role": "user", "content": "new"}])


def test_re_recording_a_request_appends_and_the_last_one_wins(tmp_path):
    cassette = tmp_path / "c.jsonl"
    RecordingProvider(ScriptedProvider([final("old")]), cassette).create(model="m", messages=[])
    RecordingProvider(ScriptedProvider([final("new")]), cassette).create(model="m", messages=[])
    assert len(cassette.read_text(encoding="utf-8").splitlines()) == 2
    assert ReplayProvider(cassette).create(model="m", messages=[])["content"][0]["text"] == "new"


# ── write-ahead, crash safety, confinement, storage ─────────────────────────


def test_a_tool_decision_is_written_before_the_tool_runs(tmp_path):
    catalog, ledger = Catalog(), Ledger(tmp_path / "ledger.jsonl")
    seen_at_run = []

    @tool(catalog, effect="read", description="Peek at the ledger while running", path_args=())
    def peek() -> str:
        seen_at_run.append([e["kind"] for e in ledger.read()])
        return "ok"

    agent = Agent(
        provider=ScriptedProvider([tool_use("peek", {}), final()]),
        model="m",
        system="s",
        prompt_id="s",
        registry=PromptRegistry(tmp_path / "approvals.jsonl"),
        catalog=catalog,
        gate=Gate(),
        ledger=ledger,
        env="dev",  # this prompt is not approved; dev is the explicit opt-out
    )
    agent.run("go")
    assert seen_at_run == [["run_start", "model_call", "tool_intent"]]


def test_a_crashed_run_still_closes_in_the_ledger(setup):
    class Broken:
        def create(self, **request):
            raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        make_agent(setup, Broken()).run("go")
    last = setup[2].read()[-1]
    assert last["kind"] == "run_end" and last["stop_reason"] == "error" and "network down" in last["error"]


def test_a_read_tool_cannot_be_pointed_outside_its_roots(tmp_path):
    catalog = Catalog()

    @tool(catalog, effect="read", description="Read a file", path_args=("path",))
    def read_file(path: str) -> str:
        return "contents"

    gate = Gate(read_roots=[tmp_path / "cards"])
    assert gate.decide(catalog.get("read_file"), {"path": str(tmp_path / "cards" / "a.md")}).verdict == "allow"
    assert gate.decide(catalog.get("read_file"), {"path": str(tmp_path / ".env")}).verdict == "deny"


def test_an_effect_the_gate_does_not_know_is_denied():
    from harness.catalog import Tool

    odd = Tool(name="x", description="", effect="delete", fn=lambda: "", input_schema={})  # bypasses register()
    assert Gate().decide(odd, {}).verdict == "deny"


def test_records_are_written_with_lf_on_every_platform(setup):
    ledger = setup[2]
    ledger.append({"kind": "x"})
    assert b"\r\n" not in ledger.path.read_bytes()


# ── security review fixes (H3, H1, H6) ──────────────────────────────────────


@pytest.mark.parametrize("env", ["production", "PROD", " prod", "", "staging"])
def test_an_env_that_is_not_dev_or_test_is_treated_as_prod(setup, env):  # H3
    agent = make_agent(setup, ScriptedProvider([final()]), system="not approved", env=env)
    with pytest.raises(UnapprovedPrompt):
        agent.run("go")


def test_the_default_env_is_prod(setup):  # H3: forgetting to pass env must not relax the control
    catalog, registry, ledger, tmp = setup
    agent = Agent(
        provider=ScriptedProvider([final()]),
        model="m",
        system="not approved",
        prompt_id="sys",
        registry=registry,
        catalog=catalog,
        gate=Gate(write_roots=[tmp]),
        ledger=ledger,
    )
    with pytest.raises(UnapprovedPrompt):
        agent.run("go")


@pytest.mark.parametrize("env", ["dev", "test", "DEV"])
def test_dev_and_test_run_an_unapproved_prompt_and_say_so(setup, env):  # H3
    result = make_agent(setup, ScriptedProvider([final("ran")]), system="not approved", env=env).run("go")
    assert result.text == "ran"
    assert setup[2].read()[0]["prompt_approved"] is False


def test_a_refused_start_is_recorded(setup):  # H3: the refusal itself is part of the audit trail
    with pytest.raises(UnapprovedPrompt):
        make_agent(setup, ScriptedProvider([final()]), system="not approved", env="prod").run("go")
    last = setup[2].read()[-1]
    assert last["kind"] == "run_refused" and last["prompt_approved"] is False


@pytest.mark.parametrize("effect", ["read", "write"])
def test_a_read_or_write_tool_must_declare_its_path_arguments(effect):  # H1
    catalog = Catalog()
    with pytest.raises(ValueError, match="path_args"):

        @tool(catalog, effect=effect, description="x")
        def open_anything(path: str) -> str:  # pragma: no cover - never registered
            return ""


def test_a_truncated_last_line_is_an_interrupted_write_and_is_ignored(tmp_path):  # H6
    from harness.storage import read_jsonl

    p = tmp_path / "l.jsonl"
    p.write_text('{"a": 1}\n{"b": 2}\n{"c": ', encoding="utf-8")
    assert list(read_jsonl(p)) == [{"a": 1}, {"b": 2}]


def test_a_corrupt_line_that_is_not_the_last_is_an_error(tmp_path):  # H6
    from harness.storage import CorruptRecord, read_jsonl

    p = tmp_path / "l.jsonl"
    p.write_text('{"a": 1}\nnot json\n{"c": 3}\n', encoding="utf-8")
    with pytest.raises(CorruptRecord, match="line 2"):
        list(read_jsonl(p))
