"""The runner (STORY-004 DR-11, DR-12, DR-15): plan → attempts in rounds → one ledger line per attempt.

- **Rounds.** Attempt 1 of every (task, configuration, model), cheapest model first, then attempt 2...
  A budget stop then leaves every contestant with the same number of attempts.
- **Resume.** The ledger is read first; an attempt already recorded is skipped (a `budget_stopped` one
  is tried again), so an interrupted run never pays twice. The spend is the sum over the ledger.
- **Budget.** Before a live run, the cost of the attempts left is projected from what this ledger has
  measured per contestant, and a projection above the cap is refused. During the run, each call
  reserves its worst case (every prompt byte as a token at the input price, plus `max_tokens` at the
  output price) before it is made, and settles the measured cost after. A call that could cross the cap
  is not made; that attempt is `budget_stopped`, with what it already spent.
- **Replay.** Offline, each attempt reads its own recording, keyed by task digest, configuration,
  model, effort and attempt number, so three attempts replay as three attempts. An unrecorded request
  stops the run.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness.providers import AnthropicProvider, Provider, RetryingProvider
from harness.replay import CassetteMiss, RecordingProvider, ReplayProvider
from harness.storage import JSONObject, append_jsonl, read_jsonl, utc_stamp
from harness.usage import PRICES, call_cost
from keysbench import arm_a, contestants
from keysbench.check import JudgeContext, fresh_workspace, grade
from keysbench.graders import TaskSpec, load_task
from keysbench.judge import judge_model_for

HERE = Path(__file__).resolve().parent
CASSETTES = HERE / "cassettes"
TASKS = HERE / "tasks"


class RunRefused(RuntimeError):
    """A command refused before anything ran: exit 2 with the reason (spec § Interface contract)."""


class BudgetStop(RuntimeError):
    pass


@dataclass(frozen=True)
class Plan:
    label: str
    cap_usd: float
    k: int
    effort: str
    models: list[str]
    configs: list[str]
    tasks: list[str]
    max_tokens: int
    max_steps: int
    not_run: list[dict[str, str]] = field(default_factory=list)
    judge: dict[str, Any] = field(default_factory=dict)
    cli: dict[str, Any] = field(default_factory=dict)
    k_by_model: dict[str, int] = field(default_factory=dict)  # the reduction order, if the budget needs it

    @classmethod
    def load(cls, path: Path) -> Plan:
        data = yaml.safe_load(path.read_text("utf-8"))
        return cls(**data)

    def k_for(self, model: str) -> int:
        return int(self.k_by_model.get(model, self.k))


@dataclass(frozen=True)
class AttemptKey:
    task_id: str
    task_sha256: str
    config: str
    model: str
    effort: str
    attempt: int

    def slug(self) -> str:
        return f"{self.config}-{self.model}-{self.effort}-{self.attempt}"


def task_digest(task_dir: Path) -> str:
    """Content digest of a task: every file under it, by relative path and bytes (DR-13)."""
    h = hashlib.sha256()
    for p in sorted(task_dir.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(task_dir).as_posix().encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def cassette_path(root: Path, key: AttemptKey) -> Path:
    return root / key.task_id / key.task_sha256[:12] / f"{key.slug()}.jsonl"


def spent(rows: list[JSONObject]) -> float:
    return sum(float(r.get("cost_usd") or 0.0) for r in rows)


# ── budget ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0


class BudgetedProvider:
    """Reserves each call's worst case before making it; settles with the measured cost after."""

    def __init__(self, inner: Provider, budget: Budget, *, model: str, max_tokens: int) -> None:
        self.inner, self.budget, self.model, self.max_tokens = inner, budget, model, max_tokens
        self.attempt_spent = 0.0

    def reservation(self, request: dict[str, Any]) -> float:
        price = PRICES[self.model]
        prompt_bytes = len(json.dumps({k: request.get(k) for k in ("system", "messages", "tools")}).encode("utf-8"))
        # One token per byte is an upper bound for this content; the price of a cache write is above
        # the input price, so the bound uses the higher of the two.
        per_input = max(price.input, price.cache_write_5m)
        return (prompt_bytes * per_input + self.max_tokens * price.output) / 1_000_000

    def create(self, **request: Any) -> JSONObject:
        worst = self.reservation(request)
        if self.budget.spent_usd + worst > self.budget.cap_usd:
            spent_now, cap = self.budget.spent_usd, self.budget.cap_usd
            raise BudgetStop(f"this call could cost up to {worst:.4f} USD; spent {spent_now:.4f} of {cap}")
        response = self.inner.create(**request)
        measured = call_cost(response.get("usage"), self.model)
        cost = worst if measured is None else measured  # an unpriced call is charged its reservation
        self.budget.spent_usd += cost
        self.attempt_spent += cost
        return response


def project(plan: Plan, ledger: list[JSONObject], remaining: list[AttemptKey]) -> float | None:
    """Projected cost of the attempts left, from this ledger's mean cost per attempt per contestant.
    Contestants with nothing measured are left out (the pilot runs on the per-call reservation)."""
    means: dict[tuple[str, str], list[float]] = {}
    for r in ledger:
        if r.get("cost_usd") is not None and r.get("outcome") != "budget_stopped":
            means.setdefault((r["config"], r["contestant"]["model"]), []).append(float(r["cost_usd"]))
    known = [k for k in remaining if (k.config, k.model) in means]
    if not known:
        return None
    return sum(sum(means[(k.config, k.model)]) / len(means[(k.config, k.model)]) for k in known)


# ── one attempt ──────────────────────────────────────────────────────────────────────────────────────


def _calls(run_calls: list[JSONObject]) -> list[JSONObject]:
    return [{k: c.get(k) for k in ("latency_s", "ttft_s", "request_id", "error", "cost_usd")} for c in run_calls]


def attempt_b(
    key: AttemptKey,
    spec: TaskSpec,
    plan: Plan,
    provider: Provider,
    out: Path,
    judge_ctx: JudgeContext | None = None,
) -> JSONObject:
    assert spec.path is not None
    row: JSONObject = {
        "kind": "attempt",
        "task_id": key.task_id,
        "task_sha256": key.task_sha256,
        "family": spec.family,
        "config": key.config,
        "contestant": {
            "model": key.model,
            "effort": key.effort,
            "harness": contestants.HARNESS,
            "harness_version": contestants.HARNESS_VERSION,
        },
        "attempt": key.attempt,
    }
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="kb-attempt-") as tmp:
        workspace = fresh_workspace(spec, Path(tmp) / "w")
        instruction = (spec.path / "instruction.md").read_text("utf-8")
        run = None
        try:
            run = contestants.run_b(
                workspace=workspace,
                instruction=instruction,
                model=key.model,
                effort=key.effort,
                provider=provider,
                ledger_path=out / "runs" / key.task_id / f"{key.slug()}.jsonl",
                max_steps=plan.max_steps,
                max_tokens=plan.max_tokens,
            )
        except BudgetStop:
            row["outcome"] = "budget_stopped"
        except CassetteMiss:
            raise
        except Exception as exc:  # the attempt failed to run: recorded, never counted as a fail
            row["outcome"], row["error"] = "error", f"{type(exc).__name__}: {exc}"[:500]
        if run is not None:
            if run.stop_reason == "refusal":
                row["outcome"] = "refused"
            elif run.stop_reason == "max_tokens":
                row["outcome"] = "truncated"
            else:
                result = grade(spec, workspace, Path(tmp) / "g", judge_ctx)
                row["outcome"] = "pass" if result.passed else "fail"
                row["grader"] = {"name": spec.family, "failed_checks": list(result.failed_checks)}
                row["judge"] = result.judge
            row["calls"] = _calls(run.calls)
            row["cost_usd"] = run.cost_usd
            row["cost_basis"] = "measured-usage" if run.cost_usd is not None else "unpriced"
            row["latency_s"] = round(run.latency_s, 3)
    if isinstance(provider, BudgetedProvider) and row.get("outcome") == "budget_stopped":
        row["cost_usd"] = round(provider.attempt_spent, 6)
        row["cost_basis"] = "measured-usage"
    row.setdefault("grader", None)
    row.setdefault("judge", None)
    row["wall_s"] = round(time.monotonic() - started, 3)
    row["at"] = utc_stamp()
    return row


CliRunner = Callable[[list[str], Path, dict[str, str]], list[str]]
MIN_CLI_BUDGET_USD = 0.05  # below this a CLI attempt is not started: it could not finish one call


def default_cli(plan: Plan) -> str:
    version = str(plan.cli.get("version", ""))
    explicit = os.environ.get("KEYSBENCH_CLAUDE")
    if explicit:
        return explicit
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "keysbench-cli" / version
    name = "claude.cmd" if os.name == "nt" else "claude"
    return str(base / "node_modules" / ".bin" / name)


def attempt_a(
    key: AttemptKey,
    spec: TaskSpec,
    plan: Plan,
    out: Path,
    *,
    live: bool,
    budget: Budget,
    cassettes: Path,
    cli_runner: CliRunner | None,
    judge_ctx: JudgeContext | None = None,
) -> JSONObject:
    assert spec.path is not None
    row: JSONObject = {
        "kind": "attempt",
        "task_id": key.task_id,
        "task_sha256": key.task_sha256,
        "family": spec.family,
        "config": key.config,
        "contestant": {
            "model": key.model,
            "effort": key.effort,
            "harness": arm_a.HARNESS[key.config],
            "harness_version": str(plan.cli.get("version", "")),
        },
        "attempt": key.attempt,
        "grader": None,
        "judge": None,
    }
    store = cassette_path(cassettes, key).with_suffix("")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="kb-attempt-") as tmp:
        workspace = fresh_workspace(spec, Path(tmp) / "w")
        if live:
            remaining = budget.cap_usd - budget.spent_usd
            if remaining < MIN_CLI_BUDGET_USD:
                row.update(outcome="budget_stopped", cost_usd=0.0, cost_basis="cli-usage", wall_s=0.0, at=utc_stamp())
                return row
            instruction = (spec.path / "instruction.md").read_text("utf-8")
            cmd = arm_a.command(
                key.config,
                model=key.model,
                effort=key.effort,
                instruction=instruction,
                remaining_usd=remaining,
                cli=default_cli(plan),
                settings=arm_a.SETTINGS[key.config],
            )
            runner_fn = cli_runner or (lambda c, w, e: arm_a.run_cli(c, w, e, int(plan.cli.get("timeout_s", 1800))))
            lines = runner_fn(cmd, workspace, arm_a.cli_env(os.environ.get("ANTHROPIC_API_KEY", "")))
            arm_a.store_attempt(store, lines, workspace, spec.editable)
        else:
            if not (store / "manifest.json").is_file():
                raise CassetteMiss(f"no stored CLI attempt at {store}")
            lines = arm_a.restore_attempt(store, workspace)
        summary = arm_a.summarise(lines, model=key.model)
        findings = arm_a.audit(lines, workspace)
        cost = summary["cost_usd"]
        if live:
            budget.spent_usd += cost if cost is not None else float(summary["cli_cost_usd"] or 0.0)
        row.update(
            calls=[{"latency_s": None, "request_id": None, "count": summary["calls"]}],
            cost_usd=cost,
            cost_basis="cli-usage" if cost is not None else "unpriced",
            cli_cost_usd=summary["cli_cost_usd"],
            cli_version=summary["cli_version"],
            latency_s=summary["latency_s"],
        )
        if findings:
            row.update(outcome="invalid", audit=findings[:20])
        elif summary["outcome"] is not None:
            row["outcome"] = summary["outcome"]
        else:
            result = grade(spec, workspace, Path(tmp) / "g", judge_ctx)
            row["outcome"] = "pass" if result.passed else "fail"
            row["grader"] = {"name": spec.family, "failed_checks": list(result.failed_checks)}
            row["judge"] = result.judge
    row["wall_s"] = round(time.monotonic() - started, 3)
    row["at"] = utc_stamp()
    return row


JudgeFactory = Callable[[AttemptKey], JudgeContext]
JUDGE_MAX_TOKENS = 8000


def judge_cassette(cassettes: Path, key: AttemptKey) -> Path:
    return cassette_path(cassettes, key).with_suffix(".judge.jsonl")


def default_judge_factory(plan: Plan, cassettes: Path, out: Path, budget: Budget, live: bool) -> JudgeFactory:
    """The judge runs during the attempt (never during scoring), on a model that is not the contestant's;
    its calls are recorded next to the attempt's own, and replayed offline."""

    def factory(key: AttemptKey) -> JudgeContext:
        model = judge_model_for(key.model, plan.judge)
        path = judge_cassette(cassettes, key)
        provider: Provider
        if live:
            inner = RecordingProvider(RetryingProvider(AnthropicProvider(stream=True, max_retries=0)), path)
            provider = BudgetedProvider(inner, budget, model=model, max_tokens=JUDGE_MAX_TOKENS)
        else:
            provider = ReplayProvider(path)
        return JudgeContext(provider, model, out / "runs" / key.task_id / f"{key.slug()}.judge.jsonl")

    return factory


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────


ProviderFactory = Callable[[AttemptKey], Provider]


def plan_keys(plan: Plan, tasks_dir: Path) -> list[AttemptKey]:
    digests = {t: task_digest(tasks_dir / t) for t in plan.tasks}
    by_price = sorted(plan.models, key=lambda m: (PRICES[m].output, m))
    keys = []
    for attempt in range(1, max(plan.k_for(m) for m in plan.models) + 1):
        for task in plan.tasks:
            for config in plan.configs:
                for model in by_price:
                    if attempt <= plan.k_for(model):
                        keys.append(AttemptKey(task, digests[task], config, model, plan.effort, attempt))
    return keys


def _recorded(ledger: list[JSONObject]) -> set[tuple[Any, ...]]:
    return {
        (r["task_sha256"], r["config"], r["contestant"]["model"], r["contestant"]["effort"], r["attempt"])
        for r in ledger
        if r.get("kind") == "attempt" and r.get("outcome") != "budget_stopped"
    }


def live_provider_factory(cassettes: Path, budget: Budget, plan: Plan) -> ProviderFactory:
    def factory(key: AttemptKey) -> Provider:
        inner = RetryingProvider(AnthropicProvider(stream=True, max_retries=0))
        recorded = RecordingProvider(inner, cassette_path(cassettes, key))
        return BudgetedProvider(recorded, budget, model=key.model, max_tokens=plan.max_tokens)

    return factory


def run(
    plan: Plan,
    *,
    tasks_dir: Path = TASKS,
    out: Path,
    live: bool = False,
    cassettes: Path = CASSETTES,
    provider_factory: ProviderFactory | None = None,
    budget_usd: float | None = None,
    cli_runner: CliRunner | None = None,
    judge_factory: JudgeFactory | None = None,
) -> list[JSONObject]:
    unpriced = [m for m in plan.models if m not in PRICES]
    if unpriced:
        raise RunRefused(f"no price for {unpriced}: a cost would be unknown")
    if live and provider_factory is None and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RunRefused("--live needs ANTHROPIC_API_KEY in the environment")
    ledger_path = out / "ledger.jsonl"
    ledger = [r for r in read_jsonl(ledger_path) if r.get("kind") == "attempt"]
    done = _recorded(ledger)
    keys = plan_keys(plan, tasks_dir)
    remaining = [k for k in keys if (k.task_sha256, k.config, k.model, k.effort, k.attempt) not in done]
    cap = plan.cap_usd if budget_usd is None else budget_usd
    budget = Budget(cap_usd=cap, spent_usd=spent(ledger))
    if live:
        projected = project(plan, ledger, remaining)
        if projected is not None and budget.spent_usd + projected > cap:
            raise RunRefused(
                f"projected {budget.spent_usd + projected:.2f} USD (spent {budget.spent_usd:.2f} + "
                f"{projected:.2f} for {len(remaining)} attempts) is above the cap of {cap:.2f}"
            )
    if provider_factory is None:
        provider_factory = (
            live_provider_factory(cassettes, budget, plan)
            if live
            else (lambda key: ReplayProvider(cassette_path(cassettes, key)))
        )
    judges = judge_factory or default_judge_factory(plan, cassettes, out, budget, live)
    rows = []
    for key in remaining:
        spec = load_task(tasks_dir / key.task_id)
        judge_ctx = judges(key) if spec.family == "judge" else None
        if key.config in ("A", "A0"):
            row = attempt_a(
                key, spec, plan, out,
                live=live, budget=budget, cassettes=cassettes, cli_runner=cli_runner, judge_ctx=judge_ctx,
            )  # fmt: skip
        elif key.config == "B":
            provider = provider_factory(key)
            if live and not isinstance(provider, BudgetedProvider):
                provider = BudgetedProvider(provider, budget, model=key.model, max_tokens=plan.max_tokens)
            row = attempt_b(key, spec, plan, provider, out, judge_ctx)
        else:
            raise RunRefused(f"unknown configuration {key.config!r}")
        append_jsonl(ledger_path, row)
        rows.append(row)
    return rows


def copy_cassettes(src: Path, dest: Path) -> None:  # pragma: no cover - a maintenance helper
    shutil.copytree(src, dest, dirs_exist_ok=True)
