"""STORY-004: the reduction order is data the code applies, and the projection accounts for task size.

Review lens 1A F4: step 2 of the reduction order ("A and A0 at k = 1") could not be expressed (k was per
model only), and the projection from a one-task pilot priced every task like the smallest one.
"""

from __future__ import annotations

import io

import pytest

from keysbench import cli, runner
from keysbench.runner import AttemptKey, Plan

FABLE, OPUS, HAIKU = "claude-fable-5-1", "claude-opus-5-5", "claude-haiku-5-5"
REDUCTION = [
    {"why": "Fable is the most expensive", "decided": True, "limits": [{"model": FABLE, "k": 1}]},
    {"why": "the CLI configurations", "decided": True, "limits": [{"config": "A0", "k": 1}, {"config": "A", "k": 1}]},
    {"why": "everything once", "decided": True, "limits": [{"k": 1}]},
    {
        "why": "recommended, not decided",
        "decided": False,
        "limits": [{"model": FABLE, "config": "A0", "k": 0}, {"model": FABLE, "config": "A", "k": 0}],
    },
]


def plan(**kw) -> Plan:
    base = {
        "label": "t",
        "cap_usd": 60.0,
        "k": 3,
        "effort": "high",
        "models": [HAIKU, FABLE],
        "configs": ["B", "A0", "A"],
        "tasks": ["KB-T"],
        "max_tokens": 32000,
        "max_steps": 12,
        "reduction": REDUCTION,
    }
    return Plan(**{**base, **kw})


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (0, {(HAIKU, "B"): 3, (HAIKU, "A"): 3, (FABLE, "B"): 3, (FABLE, "A"): 3}),
        (1, {(HAIKU, "B"): 3, (HAIKU, "A"): 3, (FABLE, "B"): 1, (FABLE, "A"): 1}),
        (2, {(HAIKU, "B"): 3, (HAIKU, "A"): 1, (FABLE, "B"): 1, (FABLE, "A"): 1}),
        (3, {(HAIKU, "B"): 1, (HAIKU, "A"): 1, (FABLE, "B"): 1, (FABLE, "A"): 1}),
    ],
)
def test_each_step_applies_its_limits_and_the_ones_before(step, expected):
    p = plan(applied_step=step)
    assert {k: p.k_for(*k) for k in expected} == expected


def test_a_step_can_take_a_contestant_out_of_a_configuration():
    p = plan(applied_step=4, reduction=[{**s, "decided": True} for s in REDUCTION])
    assert p.k_for(FABLE, "A") == 0 and p.k_for(FABLE, "B") == 1 and p.k_for(HAIKU, "A") == 1


def test_a_step_nobody_decided_cannot_be_applied():
    with pytest.raises(runner.RunRefused, match="not decided"):
        plan(applied_step=4).k_for(HAIKU, "B")


def test_the_grid_has_the_attempts_each_step_says(tmp_path):
    tasks = tmp_path / "tasks" / "KB-T"
    tasks.mkdir(parents=True)
    (tasks / "task.toml").write_text('id = "KB-T"\n', encoding="utf-8")
    assert len(runner.plan_keys(plan(applied_step=0), tmp_path / "tasks")) == 2 * 3 * 3
    assert len(runner.plan_keys(plan(applied_step=1), tmp_path / "tasks")) == 3 * 3 + 3 * 1


# ── the projection ──────────────────────────────────────────────────────────────────────────────────


def row(task, config, model, cost, outcome="pass"):
    return {
        "kind": "attempt",
        "task_id": task,
        "config": config,
        "contestant": {"model": model, "effort": "high"},
        "outcome": outcome,
        "cost_usd": cost,
    }


def key(task, config, model, attempt=1):
    return AttemptKey(task, "x", config, model, "high", attempt)


LEDGER = [
    # The reference: Haiku on B, every task (the cheap half of the pilot).
    row("KB-03", "B", HAIKU, 0.01),
    row("KB-01", "B", HAIKU, 0.05),
    # Fable on B, measured on the pilot task only.
    row("KB-03", "B", FABLE, 1.00),
]


def test_a_measured_task_is_projected_from_its_own_attempts():
    assert runner.project(plan(), LEDGER, [key("KB-03", "B", FABLE, 2)]) == pytest.approx(1.00)


def test_an_unmeasured_task_is_scaled_by_its_size_on_the_reference_contestant():
    # KB-01 costs Haiku five times KB-03, so Fable's KB-01 is projected at five times its KB-03.
    assert runner.project(plan(), LEDGER, [key("KB-01", "B", FABLE)]) == pytest.approx(5.00)


def test_a_task_nobody_measured_is_priced_like_the_largest_known_one():
    assert runner.project(plan(), LEDGER, [key("KB-02", "B", FABLE)]) == pytest.approx(5.00)


def test_a_contestant_with_nothing_measured_is_left_out():
    assert runner.project(plan(), LEDGER, [key("KB-03", "B", OPUS)]) is None


def test_the_project_command_prints_each_step_against_the_cap(tmp_path, monkeypatch):
    out = io.StringIO()
    p = tmp_path / "plan.yaml"
    p.write_text(
        "label: t\ncap_usd: 30\nk: 3\neffort: high\nmodels: [claude-haiku-5-5]\nconfigs: [B]\n"
        "tasks: [KB-03]\nmax_tokens: 32000\nmax_steps: 12\n"
        "reduction:\n  - {why: once, decided: true, limits: [{k: 1}]}\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        '{"kind": "attempt", "task_id": "KB-03", "task_sha256": "s", "config": "B", '
        '"contestant": {"model": "claude-haiku-5-5", "effort": "high"}, "attempt": 1, '
        '"outcome": "pass", "cost_usd": 0.5}\n',
        encoding="utf-8",
    )
    assert cli.main(["project", "--plan", str(p), "--ledger", str(ledger)], out=out) == 0
    text = out.getvalue()
    assert "step 0" in text and "step 1" in text and "cap 30.00" in text


def test_a_model_runs_only_in_the_configurations_the_plan_gives_it():
    # Other providers' models run in B only: A and A0 are the Claude Code CLI.
    p = plan(models=[HAIKU, "openai/gpt-5.6-sol"], configs_by_model={"openai/gpt-5.6-sol": ["B"]})
    assert p.k_for("openai/gpt-5.6-sol", "B") == 3
    assert p.k_for("openai/gpt-5.6-sol", "A") == 0 and p.k_for("openai/gpt-5.6-sol", "A0") == 0
    assert p.k_for(HAIKU, "A") == 3


def test_run_can_take_a_subset_of_the_plan(tmp_path, monkeypatch):
    # The grid runs per provider (each under its own budget) and per configuration (each run under the
    # background limit): a subset of the same plan, into the same ledger.
    seen = {}

    def fake_run(plan, **kw):
        seen["models"], seen["configs"] = plan.models, plan.configs
        return []

    monkeypatch.setattr(runner, "run", fake_run)
    p = tmp_path / "plan.yaml"
    p.write_text(
        "label: t\ncap_usd: 30\nk: 1\neffort: high\nmodels: [claude-haiku-5-5, openai/gpt-5.6-sol]\n"
        "configs: [B, A]\ntasks: [KB-03]\nmax_tokens: 32000\nmax_steps: 12\n",
        encoding="utf-8",
    )
    base = ["run", "--plan", str(p), "--out", str(tmp_path / "o")]
    assert cli.main([*base, "--only-model", "openai/gpt-5.6-sol", "--only-config", "B"], out=io.StringIO()) == 0
    assert seen == {"models": ["openai/gpt-5.6-sol"], "configs": ["B"]}
    assert cli.main([*base, "--only-model", "nope"], out=io.StringIO(), err=io.StringIO()) == 2
