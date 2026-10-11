"""STORY-004 T8: the runner and configuration B (S4-01, S4-04, S4-11, S4-12, S4-18).

The model is scripted or replayed; nothing here calls a provider. A tiny task is built in a temporary
directory: `add` must return a + b, and configuration B fixes it by writing the file with its tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.replay import CassetteMiss, RecordingProvider
from harness.storage import read_jsonl
from keysbench import runner
from keysbench.runner import Budget, BudgetedProvider, BudgetStop, Plan

TASK_TOML = """
id = "KB-T"
track = "domain"
family = "pytest"
editable = ["mod.py"]
expected_tests = ["test_hidden.py::test_add"]
timeout_s = 60
"""
HIDDEN = "from kbcall import call\n\ndef test_add():\n    assert call('mod.add(2, 3)', 'mod') == 5\n"
GOOD = "def add(a, b):\n    return a + b\n"
BAD = "def add(a, b):\n    return a - b\n"


@pytest.fixture
def tasks(tmp_path):
    t = tmp_path / "tasks" / "KB-T"
    (t / "environment").mkdir(parents=True)
    (t / "tests").mkdir()
    (t / "task.toml").write_text(TASK_TOML, encoding="utf-8")
    (t / "instruction.md").write_text("Fix add in mod.py so add(2, 3) == 5.\n", encoding="utf-8")
    (t / "environment" / "mod.py").write_text(BAD, encoding="utf-8")
    (t / "tests" / "test_hidden.py").write_text(HIDDEN, encoding="utf-8")
    return tmp_path / "tasks"


def plan(tasks_dir: Path, **kw) -> Plan:
    base = {
        "label": "test",
        "cap_usd": 60.0,
        "k": 1,
        "effort": "high",
        "models": ["claude-sonnet-5-5"],
        "configs": ["B"],
        "tasks": ["KB-T"],
        "max_tokens": 32000,
        "max_steps": 6,
        "not_run": [],
    }
    return Plan(**{**base, **kw})


def usage(inp=1000, out=200):
    return {"input_tokens": inp, "output_tokens": out, "inference_geo": "global"}


def write_call(content: str, n: int = 1) -> dict:
    return {
        "stop_reason": "tool_use",
        "content": [
            {"type": "tool_use", "id": f"t{n}", "name": "write_file", "input": {"path": "mod.py", "content": content}}
        ],
        "usage": usage(),
        "_call": {"latency_s": 1.0, "ttft_s": 0.2, "request_id": f"r{n}", "failed_tries": []},
    }


def done(stop: str = "end_turn") -> dict:
    return {
        "stop_reason": stop,
        "content": [{"type": "text", "text": "done"}],
        "usage": usage(),
        "_call": {"latency_s": 0.5, "ttft_s": 0.1, "request_id": "rz", "failed_tries": []},
    }


class Scripted:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def create(self, **request):
        self.requests.append(json.loads(json.dumps(request)))
        return self.responses.pop(0)


def by_attempt(script: dict[int, list[dict]], seen: list | None = None):
    def factory(key: runner.AttemptKey):
        p = Scripted(script[key.attempt])
        if seen is not None:
            seen.append(p)
        return p

    return factory


# ── S4-01: every row names its unit; every request carries the fixed effort ──────────────────────────


def test_s4_01_rows_name_the_unit_and_every_request_carries_the_effort(tasks, tmp_path):
    seen: list = []
    rows = runner.run(
        plan(tasks),
        tasks_dir=tasks,
        out=tmp_path / "out",
        provider_factory=by_attempt({1: [write_call(GOOD), done()]}, seen),
    )
    [row] = rows
    assert row["config"] == "B" and row["task_id"] == "KB-T" and row["task_sha256"]
    assert row["contestant"]["model"] == "claude-sonnet-5-5" and row["contestant"]["effort"] == "high"
    assert row["contestant"]["harness"] == "repo-harness" and row["contestant"]["harness_version"]
    assert row["outcome"] == "pass"
    assert all(r["output_config"]["effort"] == "high" for r in seen[0].requests)
    assert all("cache_control" in r for r in seen[0].requests)


def test_the_prompt_never_names_the_temporary_directory(tasks, tmp_path):
    seen: list = []
    runner.run(plan(tasks), tasks_dir=tasks, out=tmp_path / "out", provider_factory=by_attempt({1: [done()]}, seen))
    assert str(tmp_path) not in json.dumps(seen[0].requests)


# ── S4-04: refusal, max_tokens and errors are named, never fail ──────────────────────────────────────


@pytest.mark.parametrize(("stop", "outcome"), [("refusal", "refused"), ("max_tokens", "truncated")])
def test_s4_04_named_outcomes(tasks, tmp_path, stop, outcome):
    rows = runner.run(
        plan(tasks), tasks_dir=tasks, out=tmp_path / "out", provider_factory=by_attempt({1: [done(stop)]})
    )
    assert rows[0]["outcome"] == outcome


def test_a_wrong_answer_is_a_fail_with_its_failed_checks(tasks, tmp_path):
    rows = runner.run(
        plan(tasks), tasks_dir=tasks, out=tmp_path / "out", provider_factory=by_attempt({1: [write_call(BAD), done()]})
    )
    assert rows[0]["outcome"] == "fail"
    assert rows[0]["grader"]["failed_checks"] == ["test_add"]


# ── S4-11: the budget ────────────────────────────────────────────────────────────────────────────────


def test_s4_11_a_projection_above_the_cap_refuses_before_any_attempt(tasks, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    # A measured attempt at 25 USD for this contestant; three more would project 75 > 60.
    measured = {
        "kind": "attempt",
        "task_id": "KB-T",
        "task_sha256": "old",
        "config": "B",
        "contestant": {"model": "claude-sonnet-5-5", "effort": "high"},
        "attempt": 1,
        "outcome": "pass",
        "cost_usd": 25.0,
    }
    (out / "ledger.jsonl").write_text(json.dumps(measured) + "\n", encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="projected"):
        runner.run(plan(tasks, k=3), tasks_dir=tasks, out=out, provider_factory=by_attempt({}), live=True)


def test_s4_11_a_call_whose_worst_case_crosses_the_cap_is_not_made(tasks, tmp_path):
    inner = Scripted([done()])
    budget = Budget(cap_usd=1.0)
    provider = BudgetedProvider(inner, budget, model="claude-fable-5-1", max_tokens=32000)
    with pytest.raises(BudgetStop):
        provider.create(model="claude-fable-5-1", max_tokens=32000, messages=[{"role": "user", "content": "x"}])
    assert inner.requests == [] and budget.spent_usd == 0.0


def test_s4_11_a_stopped_attempt_keeps_what_it_spent(tasks, tmp_path):
    # First call measured at 0.50 USD; the second call's reservation (0.50 + 1.60 > 2.00) is refused.
    first = write_call(BAD)
    first["usage"] = {"input_tokens": 0, "output_tokens": 10000, "inference_geo": "global"}  # 10k x $50/MTok
    p = plan(tasks, cap_usd=2.0, models=["claude-fable-5-1"])
    rows = runner.run(
        p, tasks_dir=tasks, out=tmp_path / "out", provider_factory=by_attempt({1: [first, done()]}), live=True
    )
    assert rows[0]["outcome"] == "budget_stopped"
    assert rows[0]["cost_usd"] == pytest.approx(0.50)


# ── S4-12: replay, per attempt ───────────────────────────────────────────────────────────────────────


def test_s4_12_three_recorded_attempts_replay_as_three_attempts(tasks, tmp_path):
    script = {1: [write_call(GOOD), done()], 2: [write_call(BAD), done()], 3: [write_call(GOOD), done()]}
    cassettes = tmp_path / "cassettes"

    def recording(key):
        return RecordingProvider(Scripted(script[key.attempt]), runner.cassette_path(cassettes, key))

    p = plan(tasks, k=3)
    live = runner.run(p, tasks_dir=tasks, out=tmp_path / "live", provider_factory=recording)
    replayed = runner.run(p, tasks_dir=tasks, out=tmp_path / "replay", cassettes=cassettes)
    assert [r["outcome"] for r in live] == ["pass", "fail", "pass"]
    assert [r["outcome"] for r in replayed] == ["pass", "fail", "pass"]


def test_s4_12_an_unrecorded_request_stops_the_run(tasks, tmp_path):
    with pytest.raises(CassetteMiss):
        runner.run(plan(tasks), tasks_dir=tasks, out=tmp_path / "out", cassettes=tmp_path / "empty")


def test_s4_12_live_without_a_key_is_refused(tasks, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(runner.RunRefused, match="ANTHROPIC_API_KEY"):
        runner.run(plan(tasks), tasks_dir=tasks, out=tmp_path / "out", live=True)


# ── S4-18: resume ────────────────────────────────────────────────────────────────────────────────────


def test_s4_18_a_rerun_skips_recorded_attempts_and_keeps_the_spend(tasks, tmp_path):
    out = tmp_path / "out"
    script = {n: [write_call(GOOD), done()] for n in (1, 2, 3)}
    calls: list = []
    runner.run(plan(tasks, k=2), tasks_dir=tasks, out=out, provider_factory=by_attempt(script, calls))
    assert len(calls) == 2
    rows = runner.run(plan(tasks, k=3), tasks_dir=tasks, out=out, provider_factory=by_attempt(script, calls))
    assert len(calls) == 3  # only attempt 3 ran
    assert [r["attempt"] for r in rows] == [3]
    ledger = [r for r in read_jsonl(out / "ledger.jsonl") if r.get("kind") == "attempt"]
    assert [r["attempt"] for r in ledger] == [1, 2, 3]
    assert runner.spent(ledger) == pytest.approx(sum(r["cost_usd"] for r in ledger))


def test_attempts_run_in_rounds_cheapest_model_first(tasks, tmp_path):
    order: list = []

    def factory(key):
        order.append((key.attempt, key.model))
        return Scripted([done()])

    runner.run(
        plan(tasks, k=2, models=["claude-sonnet-5-5", "claude-haiku-5-5"]),
        tasks_dir=tasks,
        out=tmp_path / "o",
        provider_factory=factory,
    )
    assert order == [
        (1, "claude-haiku-5-5"),
        (1, "claude-sonnet-5-5"),
        (2, "claude-haiku-5-5"),
        (2, "claude-sonnet-5-5"),
    ]


def test_a_model_with_no_price_is_refused_before_anything_runs(tasks, tmp_path):
    with pytest.raises(runner.RunRefused, match="price"):
        runner.run(
            plan(tasks, models=["claude-unknown-9"]),
            tasks_dir=tasks,
            out=tmp_path / "o",
            provider_factory=by_attempt({}),
        )


# ── configurations A and A0 through the runner (the CLI is faked) ────────────────────────────────────


def fake_cli(content: str, extra_tool: dict | None = None):
    def run_cli(cmd, workspace, env):
        assert env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
        (workspace / "mod.py").write_text(content, encoding="utf-8")
        blocks = [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "mod.py"}}]
        if extra_tool:
            blocks.append(extra_tool)
        usage = {"input_tokens": 100, "output_tokens": 50, "inference_geo": "global"}
        return [
            json.dumps({"type": "system", "subtype": "init", "claude_code_version": "2.1.296"}),
            json.dumps({"type": "assistant", "message": {"id": "m1", "content": blocks, "usage": usage}}),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "total_cost_usd": 0.0007,
                    "duration_ms": 3000,
                    "duration_api_ms": 2000,
                    "num_turns": 2,
                    "usage": usage,
                }
            ),
        ]

    return run_cli


def test_configuration_a_runs_live_then_replays_from_what_it_stored(tasks, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = plan(tasks, configs=["A"], cli={"version": "2.1.296"})
    cassettes = tmp_path / "cassettes"
    [live] = runner.run(
        p, tasks_dir=tasks, out=tmp_path / "live", live=True, cassettes=cassettes, cli_runner=fake_cli(GOOD)
    )
    assert live["outcome"] == "pass" and live["contestant"]["harness"] == "claude-code-cli"
    assert live["cost_basis"] == "cli-usage" and live["cli_cost_usd"] == 0.0007
    assert live["cost_usd"] == pytest.approx((100 * 2 + 50 * 10) / 1e6)
    [replayed] = runner.run(p, tasks_dir=tasks, out=tmp_path / "replay", cassettes=cassettes)
    assert replayed["outcome"] == "pass"


def test_s4_04_configuration_a_reading_outside_the_workspace_is_invalid(tasks, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    outside = {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "../KB-01/solution/core/x.py"}}
    p = plan(tasks, configs=["A0"], cli={"version": "2.1.296"})
    [row] = runner.run(
        p, tasks_dir=tasks, out=tmp_path / "o", live=True, cassettes=tmp_path / "c", cli_runner=fake_cli(GOOD, outside)
    )
    assert row["outcome"] == "invalid" and row["audit"]


def test_configuration_a_is_not_started_without_budget_for_one_call(tasks, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = plan(tasks, configs=["A"], cli={"version": "2.1.296"}, cap_usd=0.01)
    [row] = runner.run(
        p, tasks_dir=tasks, out=tmp_path / "o", live=True, cassettes=tmp_path / "c", cli_runner=fake_cli(GOOD)
    )
    assert row["outcome"] == "budget_stopped"


# ── the run never aborts on a stop or a crash after the contestant ran (review findings 3B F3, 1B F1) ──


def _judge_task(tasks: Path) -> None:
    t = tasks / "KB-J"
    (t / "environment").mkdir(parents=True)
    (t / "task.toml").write_text(
        'id = "KB-J"\ntrack = "domain"\nfamily = "judge"\neditable = ["REVIEW.md"]\nexpected_tests = []\n'
        'timeout_s = 60\nreview_file = "REVIEW.md"\ndiff_file = "change.diff"\nrubric = "kb06.toml"\n',
        encoding="utf-8",
    )
    (t / "instruction.md").write_text("Review the change.\n", encoding="utf-8")
    (t / "environment" / "REVIEW.md").write_text("# Review\n\n(write your review here)\n", encoding="utf-8")
    (t / "environment" / "change.diff").write_text("+    return 10 ** (dbm / 20) / 1000\n", encoding="utf-8")


def write_review(n: int = 1) -> dict:
    call = write_call("Bug: `return 10 ** (dbm / 20) / 1000` uses /20; dBm to W needs /10.\n", n)
    call["content"][0]["input"]["path"] = "REVIEW.md"
    return call


def judge_answer() -> dict:
    text = json.dumps(
        {
            "verdict": "pass",
            "defect_found": True,
            "review_quote": "Bug: `return 10 ** (dbm / 20) / 1000` uses /20; dBm to W needs /10.",
        }
    )
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 1000, "output_tokens": 100, "inference_geo": "global"},
    }


def judges(budget_cap_holder: list, answers: list | None = None):
    from keysbench.check import JudgeContext

    def factory(key):
        inner = Scripted([judge_answer()] if answers is None else answers)
        provider = BudgetedProvider(inner, budget_cap_holder[0], model="claude-opus-5-5", max_tokens=8000)
        return JudgeContext(provider, "claude-opus-5-5", Path(budget_cap_holder[1]) / f"{key.slug()}.judge.jsonl")

    return factory


def test_a_judge_that_does_not_fit_the_budget_stops_the_attempt_not_the_run(tasks, tmp_path, monkeypatch):
    _judge_task(tasks)
    holder: list = [Budget(cap_usd=0.05), tmp_path]
    monkeypatch.setattr(runner, "Budget", lambda cap_usd, spent_usd=0.0: holder[0])
    p = plan(tasks, tasks=["KB-J"], cap_usd=0.05, models=["claude-haiku-5-5"])
    rows = runner.run(
        p,
        tasks_dir=tasks,
        out=tmp_path / "o",
        live=True,
        provider_factory=by_attempt({1: [write_review(), done()]}),
        judge_factory=judges(holder),
    )
    assert [r["outcome"] for r in rows] == ["budget_stopped"]
    assert rows[0]["cost_usd"] > 0  # what the contestant already spent is kept


def test_the_judges_cost_is_on_the_row_and_in_the_spend(tasks, tmp_path, monkeypatch):
    _judge_task(tasks)
    holder: list = [Budget(cap_usd=60.0), tmp_path]
    monkeypatch.setattr(runner, "Budget", lambda cap_usd, spent_usd=0.0: holder[0])
    p = plan(tasks, tasks=["KB-J"], models=["claude-haiku-5-5"])
    [row] = runner.run(
        p,
        tasks_dir=tasks,
        out=tmp_path / "o",
        live=True,
        provider_factory=by_attempt({1: [write_review(), done()]}),
        judge_factory=judges(holder),
    )
    assert row["outcome"] == "pass"
    assert row["judge_cost_usd"] == pytest.approx((1000 * 4 + 100 * 20) / 1e6)
    assert runner.spent([row]) == pytest.approx(row["cost_usd"] + row["judge_cost_usd"])


def test_a_cli_timeout_is_an_error_row_with_the_spend_seen_so_far(tasks, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    usage = {"input_tokens": 100, "output_tokens": 50, "inference_geo": "global"}
    partial = [
        json.dumps({"type": "system", "subtype": "init", "claude_code_version": "2.1.296"}),
        json.dumps({"type": "assistant", "message": {"id": "m1", "content": [], "usage": usage}}),
    ]

    def timing_out(cmd, workspace, env):
        from keysbench import arm_a

        return arm_a.close_partial(partial, reason="timeout")

    p = plan(tasks, configs=["A"], cli={"version": "2.1.296"})
    [row] = runner.run(
        p, tasks_dir=tasks, out=tmp_path / "o", live=True, cassettes=tmp_path / "c", cli_runner=timing_out
    )
    assert row["outcome"] == "error"
    assert row["cost_usd"] == pytest.approx((100 * 2 + 50 * 10) / 1e6)


def test_a_tool_error_names_only_the_relative_path_so_the_attempt_replays(tasks, tmp_path):
    # Writing under a file fails with an OS error whose text carries the temporary directory (and, on a
    # Spanish Windows, Spanish words). That text goes back to the model and into the next request, so
    # the recording would not replay (review finding 3B F4).
    bad = write_call(GOOD, 1)
    bad["content"][0]["input"]["path"] = "mod.py/x.txt"
    script = {1: [bad, write_call(GOOD, 2), done()]}
    cassettes = tmp_path / "cassettes"

    seen: list = []

    def recording(key):
        inner = Scripted(script[key.attempt])
        seen.append(inner)
        return RecordingProvider(inner, runner.cassette_path(cassettes, key))

    [live] = runner.run(plan(tasks), tasks_dir=tasks, out=tmp_path / "live", provider_factory=recording)
    sent = json.dumps(seen[0].requests)  # what the model received, tool results included
    assert "tool failed" in sent and "kb-attempt-" not in sent
    [replayed] = runner.run(plan(tasks), tasks_dir=tasks, out=tmp_path / "replay", cassettes=cassettes)
    assert live["outcome"] == replayed["outcome"] == "pass"


# ── what an attempt spends is never lost, and one attempt cannot take the whole cap (review lens 1A) ──


class FailsAfter:
    """Answers its scripted calls, then raises a non-retryable error: the spend before it was real."""

    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **request):
        if not self.responses:
            raise RuntimeError("529 overloaded after retries")
        return self.responses.pop(0)


def test_an_error_attempt_keeps_what_it_spent_and_is_retried_up_to_a_limit(tasks, tmp_path):
    out = tmp_path / "out"
    first = write_call(BAD)
    first["usage"] = {"input_tokens": 0, "output_tokens": 10000, "inference_geo": "global"}  # 0.10 USD on Sonnet
    p = plan(tasks)

    def failing(key):
        return FailsAfter([json.loads(json.dumps(first))])

    [row] = runner.run(p, tasks_dir=tasks, out=out, provider_factory=failing, live=True)
    assert row["outcome"] == "error" and row["cost_usd"] == pytest.approx(0.10)
    ledger = [r for r in read_jsonl(out / "ledger.jsonl") if r.get("kind") == "attempt"]
    assert runner.spent(ledger) == pytest.approx(0.10)
    # The run is resumed: the errored attempt runs again, once more, and then stays an error.
    assert len(runner.run(p, tasks_dir=tasks, out=out, provider_factory=failing, live=True)) == 1
    assert runner.run(p, tasks_dir=tasks, out=out, provider_factory=failing, live=True) == []
    ledger = [r for r in read_jsonl(out / "ledger.jsonl") if r.get("kind") == "attempt"]
    assert runner.spent(ledger) == pytest.approx(0.20)


def test_an_error_is_not_used_to_project_the_cost_of_the_rest(tasks, tmp_path):
    ledger = [
        {
            "task_id": "KB-T",
            "config": "B",
            "contestant": {"model": "claude-sonnet-5-5"},
            "outcome": "error",
            "cost_usd": 0.01,
        },
        {
            "task_id": "KB-T",
            "config": "B",
            "contestant": {"model": "claude-sonnet-5-5"},
            "outcome": "pass",
            "cost_usd": 1.0,
        },
    ]
    key = runner.AttemptKey("KB-T", "x", "B", "claude-sonnet-5-5", "high", 2)
    assert runner.project(plan(tasks), ledger, [key]) == pytest.approx(1.0)


def test_a_second_live_run_on_the_same_output_is_refused(tasks, tmp_path):
    out = tmp_path / "out"
    with runner.run_lock(out), pytest.raises(runner.RunRefused, match="already"):
        runner.run(plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({}), live=True)
    # Released: the next run goes ahead.
    rows = runner.run(
        plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(GOOD), done()]}), live=True
    )
    assert rows[0]["outcome"] == "pass"


def test_a_cli_attempt_is_bounded_like_configuration_b(tasks, tmp_path, monkeypatch):
    # B is bounded by max_steps calls of at most max_tokens each; the CLI gets the same bound in turns and
    # in dollars, never the whole remaining cap, and leaves one turn of headroom because the CLI's own
    # budget can be passed by the turn in flight.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    seen: list = []
    cli = fake_cli(GOOD)

    def spy(cmd, workspace, env):
        seen.append(cmd)
        return cli(cmd, workspace, env)

    p = plan(tasks, configs=["A"], cli={"version": "2.1.296"}, max_steps=6, max_tokens=32000, cap_usd=60.0)
    runner.run(p, tasks_dir=tasks, out=tmp_path / "o", live=True, cassettes=tmp_path / "c", cli_runner=spy)
    [cmd] = seen
    assert cmd[cmd.index("--max-turns") + 1] == "6"
    per_attempt = 6 * 32000 * 10 / 1e6  # max_steps x max_tokens x Sonnet 5.5's output price
    assert float(cmd[cmd.index("--max-budget-usd") + 1]) == pytest.approx(per_attempt, abs=1e-3)


def test_after_a_budget_stop_the_rest_of_the_run_is_stopped_not_attempted(tasks, tmp_path):
    # DR-11 and review lens 1B F5: once one attempt is stopped by the budget, the attempts after it are
    # recorded as stopped without a call, even if a cheaper one would still fit. Letting them run would
    # give some contestants more attempts than others on the same round.
    calls: list = []

    def factory(key):
        p = Scripted([write_call(GOOD), done()])
        calls.append(key)
        if key.model == "claude-sonnet-5-5":
            heavy = write_call(GOOD)
            heavy["usage"] = {"input_tokens": 0, "output_tokens": 50_000, "inference_geo": "global"}  # 0.50 USD
            p = Scripted([heavy, done()])
        return p

    p = plan(tasks, k=2, models=["claude-haiku-5-5", "claude-sonnet-5-5"], cap_usd=0.60)
    rows = runner.run(p, tasks_dir=tasks, out=tmp_path / "o", provider_factory=factory, live=True)
    outcomes = [(r["attempt"], r["contestant"]["model"], r["outcome"]) for r in rows]
    stopped_at = next(i for i, o in enumerate(outcomes) if o[2] == "budget_stopped")
    assert all(o[2] == "budget_stopped" for o in outcomes[stopped_at:]), outcomes
    assert all(r["cost_usd"] == 0.0 for r in rows[stopped_at + 1 :])
    assert len(rows) == 4  # every planned attempt has its line


def test_the_reservation_uses_the_requests_own_max_tokens():
    # The judge asks for 8000 tokens; reserving the contestant's 32000 for it would stop runs early.
    p = BudgetedProvider(Scripted([]), Budget(cap_usd=10.0), model="claude-opus-5-5", max_tokens=32000)
    small = p.reservation({"max_tokens": 8000, "messages": []})
    assert small < p.reservation({"max_tokens": 32000, "messages": []})
    assert p.reservation({"messages": []}) == p.reservation({"max_tokens": 32000, "messages": []})


# ── voiding attempts an instrument bug produced (live pilot, 2026-10-11) ────────────────────────────


def test_a_voided_attempt_is_run_again_and_its_spend_still_counts(tasks, tmp_path):
    # The ledger is history: a bug in the harness is corrected by an appended void line, never by an edit.
    out = tmp_path / "out"
    first = write_call(BAD)
    first["usage"] = {"input_tokens": 0, "output_tokens": 10000, "inference_geo": "global"}  # 0.10 USD
    [paid] = runner.run(
        plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [first, done()]}), live=True
    )
    voided = runner.void_attempts(out / "ledger.jsonl", configs={"B"}, reason="instrument bug: test")
    assert voided == 1
    rows = runner.run(
        plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(GOOD), done()]}), live=True
    )
    assert [r["outcome"] for r in rows] == ["pass"]  # run again
    ledger = read_jsonl(out / "ledger.jsonl")
    attempts = [r for r in ledger if r.get("kind") == "attempt"]
    assert runner.spent(attempts) == pytest.approx(paid["cost_usd"] + rows[0]["cost_usd"])  # voided spend counts
    assert runner.void_attempts(out / "ledger.jsonl", configs={"B"}, reason="again") == 1  # only the live one


def test_a_budget_stopped_attempt_is_run_again_on_resume(tasks, tmp_path):
    # Canary survivor in CI: nothing checked that a stopped attempt is retried once there is budget.
    out = tmp_path / "out"
    heavy = write_call(BAD)
    heavy["usage"] = {"input_tokens": 0, "output_tokens": 10000, "inference_geo": "global"}  # 0.50 on Fable
    p = plan(tasks, models=["claude-fable-5-1"])
    [stopped] = runner.run(
        p, tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [heavy, done()]}), live=True, budget_usd=2.0
    )
    assert stopped["outcome"] == "budget_stopped"
    [again] = runner.run(
        p, tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(GOOD), done()]}), live=True,
        budget_usd=10.0,
    )  # fmt: skip
    assert again["outcome"] == "pass"


# ── other providers through OpenRouter ──────────────────────────────────────────────────────────────


def test_a_model_with_a_provider_prefix_is_called_through_openrouter(tmp_path, monkeypatch):
    from harness.openrouter import OpenRouterProvider

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    factory = runner.live_provider_factory(tmp_path, Budget(cap_usd=1.0), plan(Path(tmp_path)))
    key = runner.AttemptKey("KB-T", "x", "B", "openai/gpt-5.6-sol", "high", 1)
    p = factory(key)
    chain = []
    while p is not None:
        chain.append(type(p).__name__)
        p = getattr(p, "inner", None)
    assert chain[-1] == OpenRouterProvider.__name__ and "RetryingProvider" in chain and "BudgetedProvider" in chain


def test_live_with_an_openrouter_model_needs_its_key(tasks, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(runner.RunRefused, match="OPENROUTER_API_KEY"):
        runner.run(plan(tasks, models=["openai/gpt-5.6-sol"]), tasks_dir=tasks, out=tmp_path / "o", live=True)


def test_a_void_can_name_the_model_too(tasks, tmp_path):
    out = tmp_path / "out"
    p = plan(tasks, models=["claude-haiku-5-5", "claude-sonnet-5-5"])
    runner.run(p, tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(GOOD), done()]}))
    assert runner.void_attempts(out / "ledger.jsonl", configs={"B"}, models={"claude-haiku-5-5"}, reason="r") == 1


def test_two_attempts_in_the_same_second_are_two_attempts(tasks, tmp_path, monkeypatch):
    # CI (Linux): the re-run of a voided attempt was recorded in the same second as the voided one, and an
    # identity of key + timestamp made the void cover it too. Each attempt line now carries its own id.
    monkeypatch.setattr(runner, "utc_stamp", lambda: "2026-10-11T10:00:00Z")
    out = tmp_path / "out"
    runner.run(plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(BAD), done()]}))
    assert runner.void_attempts(out / "ledger.jsonl", configs={"B"}, reason="bug") == 1
    runner.run(plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(GOOD), done()]}))
    standing = runner.standing(read_jsonl(out / "ledger.jsonl"))
    assert [r["outcome"] for r in standing] == ["pass"]


def test_a_provider_prefixed_model_names_a_file_not_a_folder(tmp_path):
    # Live pilot: 'openai/gpt-5.6-sol' put each recording one folder down ('B-openai/gpt-5.6-sol-...').
    key = runner.AttemptKey("KB-03", "a" * 64, "B", "openai/gpt-5.6-sol", "high", 1)
    path = runner.cassette_path(tmp_path, key)
    assert path.parent == tmp_path / "KB-03" / ("a" * 12)
    assert path.name == "B-openai--gpt-5.6-sol-high-1.jsonl"


def test_a_void_can_name_a_task_version(tasks, tmp_path):
    # Grid: a pilot attempt measured KB-05 before a hack was added to it, so under another digest.
    out = tmp_path / "out"
    runner.run(plan(tasks), tasks_dir=tasks, out=out, provider_factory=by_attempt({1: [write_call(GOOD), done()]}))
    sha = runner.task_digest(tasks / "KB-T")
    assert runner.void_attempts(out / "ledger.jsonl", configs={"B"}, reason="r", task_sha_prefix="0000") == 0
    assert runner.void_attempts(out / "ledger.jsonl", configs={"B"}, reason="r", task_sha_prefix=sha[:8]) == 1


def test_a_replayed_attempt_keeps_its_cost_but_is_not_spent_again(tasks, tmp_path):
    # Re-scoring recorded attempts after a grader fix costs nothing: the replayed row keeps the attempt's
    # cost (cost per pass stays right) and is not counted as spent a second time.
    cassettes = tmp_path / "c"

    def recording(key):
        return RecordingProvider(Scripted([write_call(GOOD), done()]), runner.cassette_path(cassettes, key))

    out = tmp_path / "out"
    [live] = runner.run(plan(tasks), tasks_dir=tasks, out=out, provider_factory=recording, live=False)
    assert runner.void_attempts(out / "ledger.jsonl", configs={"B"}, reason="grader fix") == 1
    [again] = runner.run(plan(tasks), tasks_dir=tasks, out=out, cassettes=cassettes)
    assert again["replayed"] is True and again["cost_usd"] == pytest.approx(live["cost_usd"])
    attempts = [r for r in read_jsonl(out / "ledger.jsonl") if r.get("kind") == "attempt"]
    assert runner.spent(attempts) == pytest.approx(live["cost_usd"])
