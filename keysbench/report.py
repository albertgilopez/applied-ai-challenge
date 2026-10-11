"""`keysbench score`: the ledger in, results.json and results.md out (STORY-004 DR-10, DR-13, S4-08).

Everything the conclusion rests on is computed by `core.bench_score` (pure). This module adds what is not
a function of the attempt rows (the input digests, the price-table date, the contestants not run) and
prints the Markdown. It makes no model call and opens no connection: a judge's verdict is read from the
attempt line where it was frozen. Scoring the same ledger twice gives the same bytes: `generated_at` is
the time of the last attempt, not the clock.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

from core.bench_score import score
from core.report import md_cell
from harness.storage import JSONObject, read_jsonl
from harness.usage import PRICED_REGION, PRICES_CHECKED_ON
from keysbench.runner import TASKS, Plan, cassette_path

LIMITS = (
    "Six tasks and at most three attempts per contestant: the intervals are wide. This is an instrument, "
    "not a verdict; the decision memo says how many tasks a decision would need.",
    "History tasks come from one repository whose fixes were written with an AI assistant; domain tasks use "
    "a fictitious instrument. Tasks that show an organisation's own advantage need its own repositories.",
    "One provider family. The judge (KB-06 only) is a different model of the same family, anonymised, with "
    "its evidence checked by code: bias reduced, not removed.",
    "Configurations A and A0 run the Claude Code CLI restricted and audited, not sandboxed: the audit is "
    "detection, and Python can build a path at run time that the audit cannot see.",
    "The offline measure is not the contract metric. That is cost per accepted change on real work; this is "
    "the gate before it and the regression check after it.",
)


def failure_names(tasks_dir: Path = TASKS) -> dict[str, dict[str, str]]:
    names: dict[str, dict[str, str]] = {}
    for toml in sorted(tasks_dir.glob("KB-*/task.toml")):
        raw = tomllib.loads(toml.read_text("utf-8"))
        names[str(raw["id"])] = {str(k): str(v) for k, v in (raw.get("failure_modes") or {}).items()}
    return names


def _recordings(rows: list[JSONObject], cassettes: Path) -> dict[str, str]:
    """sha256 of every recording an attempt of this ledger was (or would be) replayed from."""
    from keysbench.runner import AttemptKey

    found: dict[str, str] = {}
    for r in rows:
        key = AttemptKey(
            r["task_id"], r["task_sha256"], r["config"], r["contestant"]["model"], r["contestant"]["effort"],
            int(r["attempt"]),
        )  # fmt: skip
        base = cassette_path(cassettes, key)
        candidates = [base, base.with_suffix(".judge.jsonl")]
        store = base.with_suffix("")
        if store.is_dir():
            candidates += sorted(p for p in store.rglob("*") if p.is_file())
        for p in candidates:
            if p.is_file():
                found[p.relative_to(cassettes).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(sorted(found.items()))


def results(rows: list[JSONObject], plan: Plan, *, ledger_bytes: bytes, cassettes: Path) -> JSONObject:
    attempts = [r for r in rows if r.get("kind") == "attempt"]
    data = score(attempts, failure_names(), benchmark=plan.label)
    stamps = sorted(str(r.get("at", "")) for r in attempts)
    return {
        "benchmark": data["benchmark"],
        "generated_at": stamps[-1] if stamps else None,
        "prices_checked_on": PRICES_CHECKED_ON,
        "priced_region": PRICED_REGION,
        "tasks": data["tasks"],
        "inputs": {
            "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
            "recordings_sha256": _recordings(attempts, cassettes),
        },
        "ranking": data["ranking"],
        "memo": data["memo"],
        "cells": data["cells"],
        "by_contestant": data["by_contestant"],
        "deltas": data["deltas"],
        "not_run": list(plan.not_run),
        "limits": list(LIMITS),
    }


def _n(value: Any, places: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return md_cell(str(value))


def _interval(pair: Any) -> str:
    return "—" if not pair else f"[{pair[0]:.2f}, {pair[1]:.2f}]"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def to_markdown(data: JSONObject) -> str:
    memo = data["memo"]
    grade = memo["decision_grade"]
    lines = [
        f"# {md_cell(str(data['benchmark']))}",
        "",
        f"Tasks: {data['tasks']} · Ranking: {md_cell(str(data['ranking']))} · Prices checked on "
        f"{data['prices_checked_on']} ({data['priced_region']}) · Last attempt: {_n(data['generated_at'])}",
        "",
        "## Decision memo",
        "",
        "### Per task",
        "",
        *_table(
            ["task", "config", "model", "effort", "passes / attempts", "cost per pass (USD)", "p95 latency (s)"],
            [
                [
                    md_cell(t["task_id"]),
                    md_cell(t["config"]),
                    md_cell(t["model"]),
                    md_cell(t["effort"]),
                    f"{t['passes']} / {t['attempts']}",
                    _n(t["cost_per_pass"]),
                    _n(t["latency_p95_s"], 1),
                ]
                for t in memo["per_task"]
            ],
        ),  # fmt: skip
        "",
        "### Commodity: tasks every contestant of a configuration solved, and the cheapest that did",
        "",
        *_table(
            ["task", "config", "cheapest passing model", "cost per pass (USD)"],
            [
                [
                    md_cell(c["task_id"]),
                    md_cell(c["config"]),
                    md_cell(c["cheapest_passing_model"]),
                    _n(c["cost_per_pass"]),
                ]
                for c in memo["commodity"]
            ]
            or [["—", "—", "—", "—"]],
        ),  # fmt: skip
        "",
        "### Failure modes",
        "",
        *_table(
            ["mode", "task", "config", "model", "count"],
            [
                [md_cell(f["mode"]), md_cell(f["task_id"]), md_cell(f["config"]), md_cell(f["model"]), str(f["count"])]
                for f in memo["failure_modes"]
            ]
            or [["—", "—", "—", "—", "—"]],
        ),  # fmt: skip
        "",
        "### What a decision would need",
        "",
        f"- Measured discordance between contestants: {_n(grade['discordance_rate'])}",
        f"- Tasks needed to detect a 15-point difference: {_n(grade['tasks_needed_for_15_points'])}",
        f"- Estimated cost of such a month at this run's prices (USD): {_n(grade['est_cost_usd'], 2)}",
        f"- {md_cell(str(grade['note']))}",
        "",
        "## By contestant",
        "",
        "Ordered by name; intervals are clustered by task (the task is the independent unit).",
        "",
        *_table(
            [
                "config",
                "model",
                "effort",
                "tasks",
                "mean task pass rate",
                "95 % (task-clustered)",
                "cost per pass (USD)",
                "median latency (s)",
                "p95 latency (s)",
            ],
            [
                [
                    md_cell(c["config"]),
                    md_cell(c["model"]),
                    md_cell(c["effort"]),
                    str(c["tasks"]),
                    _n(c["mean_task_pass_rate"], 2),
                    _interval(c["task_clustered_95"]),
                    _n(c["cost_per_pass"]),
                    _n(c["latency_median_s"], 1),
                    _n(c["latency_p95_s"], 1),
                ]
                for c in data["by_contestant"]
            ],
        ),  # fmt: skip
        "",
        "## What the scaffold adds (A0 − B) and what running code adds (A − A0)",
        "",
        *_table(
            ["model", "effort", "difference", "mean paired difference", "95 % (task-clustered)", "tasks"],
            [
                [
                    md_cell(d["model"]),
                    md_cell(d["effort"]),
                    md_cell(d["kind"]),
                    _n(d["mean_paired_difference"], 2),
                    _interval(d["task_clustered_95"]),
                    str(d["tasks"]),
                ]
                for d in data["deltas"]
            ]
            or [["—", "—", "—", "—", "—", "—"]],
        ),  # fmt: skip
        "",
        "## Not run",
        "",
        *[f"- {md_cell(n['contestant'])}: {md_cell(n['reason'])}" for n in data["not_run"]],
        "",
        "## Cells",
        "",
        *_table(
            [
                "task",
                "config",
                "model",
                "passes / attempts",
                "Wilson 95 %",
                "pass^k",
                "saturated",
                "invalid",
                "cost (USD)",
            ],
            [
                [
                    md_cell(c["task_id"]),
                    md_cell(c["config"]),
                    md_cell(c["model"]),
                    f"{c['passes']} / {c['attempts']}",
                    _interval(c["wilson_95"]),
                    _n(c["pass_hat_k"].get(str(c["attempts"])), 2),
                    _n(c["saturated"]),
                    str(c["invalid"]),
                    _n(c["cost_usd_total"]),
                ]
                for c in data["cells"]
            ],
        ),  # fmt: skip
        "",
        "## Limits",
        "",
        *[f"- {md_cell(limit)}" for limit in data["limits"]],
        "",
    ]
    return "\n".join(lines)


def score_files(ledger_path: Path, out: Path, plan: Plan, *, cassettes: Path) -> JSONObject:
    raw = ledger_path.read_bytes()
    rows = [r for r in read_jsonl(ledger_path) if r.get("kind") == "attempt"]
    data = results(rows, plan, ledger_bytes=raw, cassettes=cassettes)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_bytes(
        (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    )
    (out / "results.md").write_bytes(to_markdown(data).encode("utf-8"))
    return data
