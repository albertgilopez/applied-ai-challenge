"""`python -m keysbench run | score | check-graders` (STORY-004 § Interface contract).

    run            --plan PATH --out DIR [--live] [--budget-usd N]   one ledger line per attempt; resumes
                   [--only-model M ...] [--only-config C ...]        a subset of the plan, same ledger
    score          --plan PATH --ledger PATH --out DIR               results.json, results.md; no network
    project        --plan PATH --ledger PATH                         cost at each reduction step; no network
    void           --ledger PATH --config C [--config C] --reason R  void the standing attempts of a configuration
    check-graders  [--live] [--task ID ...]                          each grader against its variants

Exit 0 on success; 1 when check-graders finds a grader that is not trusted; 2 on a refused command (an
unknown task, a model with no price, a projected run above the cap, `--live` without a key), with the
reason on stderr.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import tempfile
from pathlib import Path
from typing import TextIO

from harness.providers import AnthropicProvider, Provider, RetryingProvider
from harness.replay import CassetteMiss, RecordingProvider, ReplayProvider
from harness.storage import read_jsonl
from keysbench import report, runner
from keysbench.check import TASKS, JudgeContext, check_cassette, check_task, expected_scores
from keysbench.graders import load_task

DEFAULT_JUDGE = "claude-opus-5-5"


def _check_graders(tasks: list[str], live: bool, out: TextIO, err: TextIO) -> int:
    if live and not os.environ.get("ANTHROPIC_API_KEY"):
        err.write("check-graders --live needs ANTHROPIC_API_KEY\n")
        return 2
    bad = 0
    with tempfile.TemporaryDirectory(prefix="kb-check-") as work:
        for task_id in tasks:
            task_dir = TASKS / task_id
            if not task_dir.is_dir():
                err.write(f"unknown task {task_id}\n")
                return 2

            def judge_for(variant: str, task_id: str = task_id) -> JudgeContext:
                path = check_cassette(task_id, variant)
                provider: Provider
                if live:
                    path.unlink(missing_ok=True)  # one recording per variant: the current judge prompt
                    provider = RecordingProvider(RetryingProvider(AnthropicProvider(stream=True, max_retries=0)), path)
                else:
                    provider = ReplayProvider(path)
                return JudgeContext(provider, DEFAULT_JUDGE, Path(work) / f"{task_id}-{variant}.judge.jsonl")

            try:
                got = check_task(task_dir, Path(work), judge_for)
            except CassetteMiss as exc:
                err.write(f"{task_id}: {exc} (record once with check-graders --live)\n")
                return 2
            want = expected_scores(load_task(task_dir))
            status = "ok" if got == want else "NOT TRUSTED"
            bad += got != want
            out.write(f"{task_id}: {status} {got}\n")
    return 1 if bad else 0


def _project(plan: runner.Plan, ledger_path: Path, out: TextIO) -> int:
    ledger = [r for r in read_jsonl(ledger_path) if r.get("kind") == "attempt"]
    out.write(f"{plan.label}: spent {runner.spent(ledger):.2f} USD, cap {plan.cap_usd:.2f}\n")
    for s in runner.projection_table(plan, ledger, TASKS):
        total = "n/a (nothing measured)" if s["total_usd"] is None else f"{s['total_usd']:8.2f} USD"
        verdict = "" if s["total_usd"] is None else ("fits" if s["total_usd"] <= plan.cap_usd else "OVER")
        note = "" if s["decided"] else "  [not decided]"
        out.write(
            f"step {s['step']}: {s['attempts']:4} attempts, {s['left']:4} left ({s['unmeasured']} unmeasured), "
            f"projected {total} {verdict}  {s['why']}{note}\n"
        )
    applied = "applied" if plan.applied_step else "none applied"
    out.write(f"step in the plan: {plan.applied_step} ({applied}); unmeasured contestants are not in the total\n")
    return 0


def main(argv: list[str] | None = None, out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    ap = argparse.ArgumentParser(prog="keysbench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--plan", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--live", action="store_true")
    r.add_argument("--budget-usd", type=float)
    r.add_argument("--only-model", action="append")
    r.add_argument("--only-config", action="append")
    s = sub.add_parser("score")
    s.add_argument("--plan", type=Path, required=True)
    s.add_argument("--ledger", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("void")
    v.add_argument("--ledger", type=Path, required=True)
    v.add_argument("--config", action="append", required=True)
    v.add_argument("--reason", required=True)
    v.add_argument("--model", action="append")
    v.add_argument("--task-sha", help="digest prefix of the task version")
    pr = sub.add_parser("project")
    pr.add_argument("--plan", type=Path, required=True)
    pr.add_argument("--ledger", type=Path, required=True)
    c = sub.add_parser("check-graders")
    c.add_argument("--live", action="store_true")
    c.add_argument("--task", action="append")
    a = ap.parse_args(argv)

    if a.cmd == "void":
        models = set(a.model) if a.model else None
        n = runner.void_attempts(
            a.ledger, configs=set(a.config), reason=a.reason, models=models, task_sha_prefix=a.task_sha
        )
        out.write(f"voided {n} attempts of {sorted(a.config)}: {a.reason}\n")
        return 0
    if a.cmd == "check-graders":
        tasks = a.task or sorted(p.name for p in TASKS.glob("KB-*") if p.is_dir())
        return _check_graders(tasks, a.live, out, err)

    plan = runner.Plan.load(a.plan)
    if a.cmd == "project":
        return _project(plan, a.ledger, out)
    unknown = [t for t in plan.tasks if not (TASKS / t).is_dir()]
    if unknown:
        err.write(f"unknown task(s): {unknown}\n")
        return 2
    if a.cmd == "score":
        data = report.score_files(a.ledger, a.out, plan, cassettes=runner.CASSETTES)
        out.write(f"scored {sum(c['attempts'] for c in data['cells'])} attempts into {a.out}\n")
        return 0
    try:
        if a.only_model or a.only_config:
            # A subset of the same plan into the same ledger: per provider (each under its own budget) or per
            # configuration (each run shorter). Unknown names are refused rather than silently ignored.
            unknown = sorted(set(a.only_model or []) - set(plan.models))
            unknown += sorted(set(a.only_config or []) - set(plan.configs))
            if unknown:
                err.write(f"refused: not in the plan: {unknown}\n")
                return 2
            plan = dataclasses.replace(
                plan,
                models=[m for m in plan.models if not a.only_model or m in a.only_model],
                configs=[c for c in plan.configs if not a.only_config or c in a.only_config],
            )
        rows = runner.run(plan, out=a.out, live=a.live, budget_usd=a.budget_usd)
    except runner.RunRefused as exc:
        err.write(f"refused: {exc}\n")
        return 2
    except CassetteMiss as exc:
        err.write(f"stopped: {exc}\n")
        return 2
    stopped = sum(r["outcome"] == "budget_stopped" for r in rows)
    out.write(f"{len(rows)} attempts recorded in {a.out / 'ledger.jsonl'}; budget_stopped: {stopped}\n")
    return 2 if stopped and not any(r["outcome"] != "budget_stopped" for r in rows) else 0
