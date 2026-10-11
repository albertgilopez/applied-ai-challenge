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
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness.openrouter import OpenRouterProvider
from harness.providers import AnthropicProvider, Provider, RetryingProvider
from harness.replay import CassetteMiss, RecordingProvider, ReplayProvider
from harness.storage import JSONObject, append_jsonl, read_jsonl, utc_stamp
from harness.usage import PRICES, call_cost
from keysbench import arm_a, contestants, judge
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
    # The reduction order, decided before the run: ordered, cumulative steps, each with its reason and
    # its limits ({model?, config?, k}). `applied_step` says how many apply; a step nobody has decided
    # (`decided: false`) cannot be applied, only projected.
    reduction: list[dict[str, Any]] = field(default_factory=list)
    applied_step: int = 0
    # The configurations a model runs in, when not all of them: other providers' models run in B only,
    # because A and A0 are the Claude Code CLI.
    configs_by_model: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Plan:
        data = yaml.safe_load(path.read_text("utf-8"))
        return cls(**data)

    def k_at(self, model: str, config: str, step: int) -> int:
        """Attempts per task for a contestant with the first `step` reduction steps applied."""
        if model in self.configs_by_model and config not in self.configs_by_model[model]:
            return 0
        k = self.k
        for s in self.reduction[:step]:
            for limit in s.get("limits", []):
                if limit.get("model", model) == model and limit.get("config", config) == config:
                    k = min(k, int(limit["k"]))
        return k

    def k_for(self, model: str, config: str) -> int:
        undecided = [i + 1 for i, s in enumerate(self.reduction[: self.applied_step]) if not s.get("decided")]
        if undecided:
            raise RunRefused(f"reduction step {undecided[0]} is not decided; it can be projected, not applied")
        return self.k_at(model, config, self.applied_step)


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
    """What a ledger has spent: the contestants' calls and the judge's (KB-06), stopped attempts included."""
    return sum(float(r.get("cost_usd") or 0.0) + float(r.get("judge_cost_usd") or 0.0) for r in rows)


def _grade_into(row: JSONObject, spec: TaskSpec, workspace: Path, dest: Path, judge_ctx: JudgeContext | None) -> None:
    """Grade, inside the attempt: a judge call the budget cannot hold makes this attempt `budget_stopped`,
    and a grader that crashes makes it `error`. Neither aborts the run, so the ledger always gets its line
    and a resume never pays for the same attempt twice (DR-11, DR-15)."""
    try:
        result = grade(spec, workspace, dest, judge_ctx)
    except BudgetStop:
        row["outcome"] = "budget_stopped"
        return
    except CassetteMiss:
        raise
    except Exception as exc:
        row["outcome"], row["error"] = "error", f"grader: {type(exc).__name__}: {exc}"[:500]
        return
    row["outcome"] = "pass" if result.passed else "fail"
    row["grader"] = {"name": spec.family, "failed_checks": list(result.failed_checks)}
    row["judge"] = result.judge
    if result.judge is not None:
        row["judge_cost_usd"] = result.judge.get("cost_usd")


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
        # The request's own max_tokens when it has one (the judge asks for fewer than a contestant);
        # a separate constant for it had already been written twice (review lens 1B F4).
        max_tokens = int(request.get("max_tokens") or self.max_tokens)
        return (prompt_bytes * per_input + max_tokens * price.output) / 1_000_000

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


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def project(plan: Plan, ledger: list[JSONObject], remaining: list[AttemptKey]) -> float | None:
    """Projected cost of the attempts left, from what this ledger measured.

    A (task, contestant) already measured is projected at its own mean. Otherwise the contestant's mean
    is scaled by task size: the size of a task is what it cost the reference contestant (the one measured
    on the most tasks; in the pilot, Haiku on B across every task), and a task nobody measured is priced
    like the largest one known. The scaling assumes a task that is bigger for one model is bigger for all
    in the same proportion: an assumption, stated in the report. A one-task pilot priced every task like
    the smallest one (review lens 1A F4). Contestants with nothing measured are left out.
    Stopped and errored attempts are not used: they did not run to the end."""
    seen: dict[tuple[str, str, str], list[float]] = {}
    for r in ledger:
        if r.get("cost_usd") is not None and r.get("outcome") not in ("budget_stopped", "error"):
            seen.setdefault((r["task_id"], r["config"], r["contestant"]["model"]), []).append(float(r["cost_usd"]))
    if not seen:
        return None
    by_contestant: dict[tuple[str, str], dict[str, float]] = {}
    for (task, config, model), costs in seen.items():
        by_contestant.setdefault((config, model), {})[task] = _mean(costs)
    reference = max(by_contestant.values(), key=len)
    largest = max(reference.values())

    def size(task: str) -> float:
        return reference.get(task, largest)

    total, known = 0.0, 0
    for k in remaining:
        measured = by_contestant.get((k.config, k.model))
        if measured is None:
            continue
        known += 1
        if k.task_id in measured:
            total += measured[k.task_id]
        else:
            per_size = _mean(
                [c / size(t) for t, c in measured.items() if size(t) > 0] or [_mean(list(measured.values()))]
            )
            total += per_size * size(k.task_id)
    return total if known else None


def projection_table(plan: Plan, ledger: list[JSONObject], tasks_dir: Path) -> list[JSONObject]:
    """The cost of the run at every reduction step, from what the ledger measured: the number that is
    looked at before the grid, derived rather than estimated in prose."""
    done = _recorded(ledger)
    already = spent(ledger)
    out = []
    for step in range(len(plan.reduction) + 1):
        keys = plan_keys(plan, tasks_dir, step=step)
        left = [k for k in keys if (k.task_sha256, k.config, k.model, k.effort, k.attempt) not in done]
        measured = {(r["config"], r["contestant"]["model"]) for r in ledger if r.get("cost_usd") is not None}
        projected = project(plan, ledger, left)
        out.append(
            {
                "step": step,
                "why": "" if step == 0 else plan.reduction[step - 1].get("why", ""),
                "decided": step == 0 or bool(plan.reduction[step - 1].get("decided")),
                "attempts": len(keys),
                "left": len(left),
                "unmeasured": sum((k.config, k.model) not in measured for k in left),
                "total_usd": None if projected is None else round(already + projected, 2),
            }
        )
    return out


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
                _grade_into(row, spec, workspace, Path(tmp) / "g", judge_ctx)
            row["calls"] = _calls(run.calls)
            row["cost_usd"] = run.cost_usd
            row["cost_basis"] = "measured-usage" if run.cost_usd is not None else "unpriced"
            row["latency_s"] = round(run.latency_s, 3)
    if isinstance(provider, BudgetedProvider) and run is None:
        # The attempt stopped or crashed before it returned: what its calls cost is still on the bill
        # (review lens 1A F2: a 0.41 USD call followed by an error was recorded as 0).
        row["cost_usd"] = round(provider.attempt_spent, 6)
        row["cost_basis"] = "measured-usage"
    row.setdefault("grader", None)
    row.setdefault("judge", None)
    row["wall_s"] = round(time.monotonic() - started, 3)
    row["at"] = utc_stamp()
    return row


CliRunner = Callable[[list[str], Path, dict[str, str]], list[str]]


def cli_budget(plan: Plan, model: str, remaining: float) -> float:
    """What one CLI attempt may spend: B's own bound (max_steps calls of at most max_tokens output each),
    and never more than the remaining cap less one turn, because the CLI documents that its budget can be
    passed by the turn in flight. Before this, the first CLI attempt was handed the whole cap
    (review lens 1A F3)."""
    one_turn = plan.max_tokens * PRICES[model].output / 1_000_000
    return max(0.0, min(plan.max_steps * one_turn, remaining - one_turn))


MIN_CLI_BUDGET_USD = 0.05  # below this a CLI attempt is not started: it could not finish one call


def default_cli(plan: Plan, *, windows: bool | None = None) -> str:
    version = str(plan.cli.get("version", ""))
    explicit = os.environ.get("KEYSBENCH_CLAUDE")
    if explicit:
        return explicit
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "keysbench-cli" / version
    if (os.name == "nt") if windows is None else windows:
        # The executable itself, never the .cmd shim: cmd.exe would cut the multi-line prompt and every
        # flag after it (review finding 3B F1).
        return str(base / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")
    return str(base / "node_modules" / ".bin" / "claude")


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
            remaining = cli_budget(plan, key.model, budget.cap_usd - budget.spent_usd)
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
                max_turns=plan.max_steps,
                cli=default_cli(plan),
                settings=arm_a.SETTINGS[key.config],
            )
            runner_fn = cli_runner or (lambda c, w, e: arm_a.run_cli(c, w, e, int(plan.cli.get("timeout_s", 1800))))
            key_value = os.environ.get("ANTHROPIC_API_KEY", "")
            lines = runner_fn(cmd, workspace, arm_a.cli_env(key_value))
            arm_a.store_attempt(store, lines, workspace, spec.editable, secrets=(key_value,))
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
            num_turns=summary["num_turns"],
            permission_denials=len(summary["permission_denials"]),
            cli_version=summary["cli_version"],
            latency_s=summary["latency_s"],
        )
        if findings:
            row.update(outcome="invalid", audit=findings[:20])
        elif summary["outcome"] is not None:
            row["outcome"] = summary["outcome"]
        else:
            _grade_into(row, spec, workspace, Path(tmp) / "g", judge_ctx)
    row["wall_s"] = round(time.monotonic() - started, 3)
    row["at"] = utc_stamp()
    return row


def via_openrouter(model: str) -> bool:
    """Other providers' models are named with their provider (`openai/...`) and called through OpenRouter."""
    return "/" in model


def live_retrying(model: str = "") -> RetryingProvider:
    """Five retries, 4 s doubling (up to about two minutes in all) or what the server asks for: an overload
    shorter than that is not an `error` row (review lens 1A F2: two retries at 2 s and 4 s gave up on a 529
    after about 6 s)."""
    inner: Provider
    if via_openrouter(model):
        inner = OpenRouterProvider(api_key=os.environ.get("OPENROUTER_API_KEY", ""))
    else:
        inner = AnthropicProvider(stream=True, max_retries=0)
    return RetryingProvider(inner, retries=5, backoff_s=4.0)


JudgeFactory = Callable[[AttemptKey], JudgeContext]


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
            inner = RecordingProvider(live_retrying(), path)
            provider = BudgetedProvider(inner, budget, model=model, max_tokens=judge.MAX_TOKENS)
        else:
            provider = ReplayProvider(path)
        return JudgeContext(provider, model, out / "runs" / key.task_id / f"{key.slug()}.judge.jsonl")

    return factory


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────


ProviderFactory = Callable[[AttemptKey], Provider]


def plan_keys(plan: Plan, tasks_dir: Path, *, step: int | None = None) -> list[AttemptKey]:
    """The attempts of a plan, in rounds (attempt 1 of everything, then attempt 2...), cheapest model first.
    `step` projects another reduction step without applying it."""
    digests = {t: task_digest(tasks_dir / t) for t in plan.tasks}
    by_price = sorted(plan.models, key=lambda m: (PRICES[m].output, m))

    def k(model: str, config: str) -> int:
        return plan.k_for(model, config) if step is None else plan.k_at(model, config, step)

    rounds = max((k(m, c) for m in plan.models for c in plan.configs), default=0)
    keys = []
    for attempt in range(1, rounds + 1):
        for task in plan.tasks:
            for config in plan.configs:
                for model in by_price:
                    if attempt <= k(model, config):
                        keys.append(AttemptKey(task, digests[task], config, model, plan.effort, attempt))
    return keys


def _attempt_id(r: JSONObject) -> tuple[Any, ...]:
    """One recorded attempt: its key plus when it was recorded (a re-run of the same key is another row)."""
    c = r.get("contestant") or {}
    return (r.get("task_sha256"), r.get("config"), c.get("model", r.get("model")), c.get("effort", r.get("effort")),
            r.get("attempt"), r.get("at"))  # fmt: skip


def voided_ids(rows: list[JSONObject]) -> set[tuple[Any, ...]]:
    return {_attempt_id(a) for r in rows if r.get("kind") == "void" for a in r.get("attempts") or []}


def standing(rows: list[JSONObject]) -> list[JSONObject]:
    """Attempts not voided. The ledger is history: an attempt an instrument bug produced is never edited
    or removed, it is voided by an appended line, and a resume runs it again."""
    gone = voided_ids(rows)
    return [r for r in rows if r.get("kind") == "attempt" and _attempt_id(r) not in gone]


def void_attempts(ledger_path: Path, *, configs: set[str], reason: str) -> int:
    """Append one void line for every standing attempt of `configs`; returns how many. What they cost is
    still spent (`spent` counts every attempt line)."""
    rows = list(read_jsonl(ledger_path))
    targets = [r for r in standing(rows) if r.get("config") in configs]
    if targets:
        ids = [
            {
                "task_sha256": r["task_sha256"],
                "config": r["config"],
                "model": r["contestant"]["model"],
                "effort": r["contestant"]["effort"],
                "attempt": r["attempt"],
                "at": r.get("at"),
            }  # fmt: skip
            for r in targets
        ]
        append_jsonl(ledger_path, {"kind": "void", "reason": reason, "at": utc_stamp(), "attempts": ids})
    return len(targets)


MAX_ERROR_TRIES = 2  # an attempt that errors (an outage, a crash) is run again once, then left as an error


def _recorded(ledger: list[JSONObject]) -> set[tuple[Any, ...]]:
    """Keys a resume skips. A `budget_stopped` attempt is run again when there is budget; an `error` one
    is run again until it has errored MAX_ERROR_TRIES times. Every row stays in the ledger, so what each
    try spent is counted."""
    errors: dict[tuple[Any, ...], int] = {}
    done = set()
    for r in ledger:
        if r.get("kind") != "attempt":
            continue
        k = (r["task_sha256"], r["config"], r["contestant"]["model"], r["contestant"]["effort"], r["attempt"])
        if r.get("outcome") == "error":
            errors[k] = errors.get(k, 0) + 1
            if errors[k] >= MAX_ERROR_TRIES:
                done.add(k)
        elif r.get("outcome") != "budget_stopped":
            done.add(k)
    return done


@contextmanager
def run_lock(out: Path) -> Iterator[None]:
    """One live run per output directory: two would each spend the whole remaining cap."""
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".run.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RunRefused(f"a run is already writing to {out} (remove {lock.name} if no run is going on)") from exc
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def live_provider_factory(cassettes: Path, budget: Budget, plan: Plan) -> ProviderFactory:
    def factory(key: AttemptKey) -> Provider:
        recorded = RecordingProvider(live_retrying(key.model), cassette_path(cassettes, key))
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
    openrouter = [m for m in plan.models if via_openrouter(m)]
    if live and provider_factory is None and openrouter and not os.environ.get("OPENROUTER_API_KEY"):
        raise RunRefused(f"--live with {openrouter} needs OPENROUTER_API_KEY in the environment")
    if live:
        with run_lock(out):
            return _run(plan, tasks_dir, out, live, cassettes, provider_factory, budget_usd, cli_runner, judge_factory)
    return _run(plan, tasks_dir, out, live, cassettes, provider_factory, budget_usd, cli_runner, judge_factory)


def _run(
    plan: Plan,
    tasks_dir: Path,
    out: Path,
    live: bool,
    cassettes: Path,
    provider_factory: ProviderFactory | None,
    budget_usd: float | None,
    cli_runner: CliRunner | None,
    judge_factory: JudgeFactory | None,
) -> list[JSONObject]:
    ledger_path = out / "ledger.jsonl"
    history = list(read_jsonl(ledger_path))  # an iterator: read once, used twice
    every = [r for r in history if r.get("kind") == "attempt"]  # spent: voided attempts were paid for too
    ledger = standing(history)
    done = _recorded(ledger)
    keys = plan_keys(plan, tasks_dir)
    remaining = [k for k in keys if (k.task_sha256, k.config, k.model, k.effort, k.attempt) not in done]
    cap = plan.cap_usd if budget_usd is None else budget_usd
    budget = Budget(cap_usd=cap, spent_usd=spent(every))
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
    stopped = False
    for key in remaining:
        if stopped:
            # DR-11: once the budget stops one attempt, the rest are recorded as stopped without a call.
            # A cheaper attempt that would still fit is not made: it would give some contestants more
            # attempts than others in the same round (review lens 1B F5). A resume with more budget runs them.
            row = not_started(key, plan)
            append_jsonl(ledger_path, row)
            rows.append(row)
            continue
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
        stopped = live and row.get("outcome") == "budget_stopped"
    return rows


def not_started(key: AttemptKey, plan: Plan) -> JSONObject:
    harness = contestants.HARNESS if key.config == "B" else arm_a.HARNESS.get(key.config, "")
    version = contestants.HARNESS_VERSION if key.config == "B" else str(plan.cli.get("version", ""))
    return {
        "kind": "attempt",
        "task_id": key.task_id,
        "task_sha256": key.task_sha256,
        "config": key.config,
        "contestant": {"model": key.model, "effort": key.effort, "harness": harness, "harness_version": version},
        "attempt": key.attempt,
        "outcome": "budget_stopped",
        "error": "not started: the budget stopped an earlier attempt of this run",
        "cost_usd": 0.0,
        "cost_basis": "not-started",
        "grader": None,
        "judge": None,
        "at": utc_stamp(),
    }
