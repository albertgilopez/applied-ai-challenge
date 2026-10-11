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
from keysbench.runner import TASKS, Plan, cassette_path, standing

LIMITS = (
    "Six tasks and at most three attempts per contestant: the intervals are wide. This is an instrument, "
    "not a verdict; the decision memo says how many tasks a decision would need.",
    "History tasks come from one repository whose fixes were written with an AI assistant; domain tasks use "
    "a fictitious instrument. Tasks that show an organisation's own advantage need its own repositories.",
    "Configuration B has models from four providers (three through OpenRouter); A0 and A run Anthropic's "
    "CLI, so only Anthropic models. Qwen3 Coder Next has no reasoning setting: the effort is sent and has "
    "no effect.",
    "The judge (KB-06 only) is an Anthropic model, anonymised, never the contestant. Code checks that its "
    "quote is in the review; whether the quote is the planted defect is the judge's call (a word-level check "
    "rejected 14 of 21 correct reviews and was removed). Bias reduced, not removed.",
    "Configuration A0 runs the Claude Code CLI restricted and audited, not sandboxed, with file tools only. "
    "Whether code execution changes the picture is not answered this month: configuration A (the CLI with "
    "Python) ran and was voided, because the CLI's permission matcher refused most of the Python the rule "
    "allowed; the fix is the CLI in a container.",
    "The offline measure is not the contract metric. That is cost per accepted change on real work; this is "
    "the gate before it and the regression check after it.",
)


def failure_names(tasks_dir: Path = TASKS) -> dict[str, dict[str, str]]:
    names: dict[str, dict[str, str]] = {}
    for toml in sorted(tasks_dir.glob("KB-*/task.toml")):
        raw = tomllib.loads(toml.read_text("utf-8"))
        names[str(raw["id"])] = {str(k): str(v) for k, v in (raw.get("failure_modes") or {}).items()}
    return names


CONFIGS = {
    "B": "the API called directly from this repository's agent loop, with three file tools (list, read, "
    "write) and no code execution",
    "A0": "Claude Code (the CLI, as shipped) with its file tools, no code execution",
    "A": "Claude Code with its file tools and Python",
}
TERMS = {
    "pass rate": "passes / attempts in one cell (one task, one contestant)",
    "pass^k": "the chance that all k attempts pass, the reliability of a contestant on a task",
    "task-clustered 95 % interval": "a t interval over per-task pass rates: the task, not the attempt, is "
    "the independent unit, so the interval is as wide as the number of tasks makes it",
    "cost per pass": "everything the contestant's attempts cost (USD, measured usage at list prices) / passes",
    "discordance": "the chance that one attempt of each of two contestants disagree on a task; it sets "
    "how many tasks a difference between them needs to be detected",
}


def task_legend(task_ids: list[str], tasks_dir: Path = TASKS) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for t in task_ids:
        toml = tasks_dir / t / "task.toml"
        raw = tomllib.loads(toml.read_text("utf-8")) if toml.is_file() else {}
        out[t] = {"title": str(raw.get("title", "")), "track": str(raw.get("track", ""))}
    return out


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
    attempts = standing(rows)
    voids: dict[str, int] = {}
    for r in rows:
        if r.get("kind") == "void":
            voids[str(r.get("reason", ""))] = voids.get(str(r.get("reason", "")), 0) + len(r.get("attempts") or [])
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
        "reduction": {
            "applied_step": plan.applied_step,
            "applied": [
                {"why": s.get("why", ""), "limits": s.get("limits", [])} for s in plan.reduction[: plan.applied_step]
            ],
            "k": {c: {m: plan.k_at(m, c, plan.applied_step) for m in plan.models} for c in plan.configs},
        },
        "not_run": list(plan.not_run),
        "voided": [{"count": n, "reason": reason} for reason, n in sorted(voids.items())],
        "limits": list(LIMITS),
        "legend": {"tasks": task_legend(sorted({c["task_id"] for c in data["cells"]})), "configs": CONFIGS},
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


def _who(config: str, model: str) -> str:
    return f"{config} · {model}"


def _answer(data: JSONObject) -> list[str]:
    """The memo's first section, every sentence computed from the results: what a reader who will not read
    the tables needs (review lens 2B F2). No contestant is ranked (DR-10)."""
    legend = data.get("legend", {}).get("tasks", {})
    tracks: dict[str, int] = {}
    for t in legend.values():
        tracks[t["track"] or "unknown"] = tracks.get(t["track"] or "unknown", 0) + 1
    track_text = ", ".join(f"{n} {track}" for track, n in sorted(tracks.items()))
    n_tasks = int(data["tasks"])
    rule = "the scorer defines none for 8 tasks or fewer" if n_tasks <= 8 else "no ranking rule is defined"
    out = [f"- **{n_tasks} tasks** ({track_text}). No ranking: {rule}."]
    cells = data["cells"]
    unsolved = sorted({c["task_id"] for c in cells} - {c["task_id"] for c in cells if c["passes"]})
    if unsolved:
        out.append(f"- **Solved by no contestant:** {', '.join(md_cell(t) for t in unsolved)}.")
    for c in data["memo"]["commodity"]:
        out.append(
            f"- **Solved by every {md_cell(c['config'])} contestant:** {md_cell(c['task_id'])}; the cheapest that "
            f"did is {md_cell(c['cheapest_passing_model'])} at {_n(c['cost_per_pass'])} USD per pass."
        )
    for d in data["deltas"]:
        if d["kind"] != "A-B":
            continue
        lo, hi = d["task_clustered_95"]
        if lo > 0 or hi < 0:
            verdict = "a difference these tasks show"
        elif lo == hi == 0:
            verdict = "no difference on these tasks"
        else:
            verdict = "not separable on these tasks"
        out.append(
            f"- **Claude Code against the API loop (A − B), {md_cell(d['model'])}:** "
            f"{d['mean_paired_difference'] * 100:+.0f} points of pass rate over {d['tasks']} tasks, "
            f"95 % [{lo * 100:+.0f}, {hi * 100:+.0f}]: {verdict}."
        )
    pairs = data["memo"]["decision_grade"].get("pairs") or []
    if pairs:
        p = pairs[0]
        n15 = p["tasks_needed"]["15"]
        need = (
            "a 15-point difference could not occur at their measured discordance"
            if n15 is None
            else f"a gap seen on {p['tasks']} tasks is not conclusive: detecting 15 points reliably (power 0.8) "
            f"would need {n15} paired tasks"
            + ("" if p["est_cost_usd"] is None else f", about {p['est_cost_usd']:.2f} USD a month for the two")
        )
        gap = abs(p["mean_difference"]) * 100
        ahead = p["x"] if p["mean_difference"] > 0 else p["y"]
        apart = "level" if gap == 0 else f"{gap:.0f} points apart, {md_cell(ahead)} ahead"
        out.append(
            f"- **Hardest pair to tell apart:** {md_cell(_who(p['config'], p['x']))} and "
            f"{md_cell(_who(p['config'], p['y']))}, {apart} over {p['tasks']} tasks; {need}."
        )
    return out


def _glance(data: JSONObject) -> list[str]:
    cells = data["cells"]
    who = sorted({(c["config"], c["model"]) for c in cells})
    tasks = sorted({c["task_id"] for c in cells})
    at = {(c["task_id"], c["config"], c["model"]): f"{c['passes']} / {c['attempts']}" for c in cells}
    return _table(
        ["task", *[md_cell(_who(*w)) for w in who]],
        [[md_cell(t), *[at.get((t, *w), "—") for w in who]] for t in tasks],
    )


def _legend(data: JSONObject) -> list[str]:
    legend = data.get("legend", {})
    return [
        *_table(
            ["task", "track", "what it asks"],
            [[md_cell(t), md_cell(v["track"]), md_cell(v["title"])] for t, v in legend.get("tasks", {}).items()],
        ),
        "",
        "Configurations (the same models in each):",
        "",
        *[f"- {md_cell(k)}: {md_cell(v)}" for k, v in legend.get("configs", {}).items()],
        "",
        "Terms:",
        "",
        *[f"- {md_cell(k)}: {md_cell(v)}" for k, v in TERMS.items()],
    ]


def to_markdown(data: JSONObject) -> str:
    memo = data["memo"]
    grade = memo["decision_grade"]
    tracks = {t: v["track"] for t, v in data.get("legend", {}).get("tasks", {}).items()}
    lines = [
        f"# {md_cell(str(data['benchmark']))}",
        "",
        f"Tasks: {data['tasks']} · Ranking: {md_cell(str(data['ranking']))} · Prices checked on "
        f"{data['prices_checked_on']} ({data['priced_region']}) · Last attempt: {_n(data['generated_at'])}",
        "",
        "## Decision memo",
        "",
        "### Answer",
        "",
        *_answer(data),
        "",
        "### At a glance: passes / attempts",
        "",
        *_glance(data),
        "",
        "### Reading this",
        "",
        *_legend(data),
        "",
        "### Per task",
        "",
        *_table(
            [
                "task",
                "track",
                "config",
                "model",
                "effort",
                "passes / attempts",
                "cost per pass (USD)",
                "p95 latency (s)",
            ],
            [
                [
                    md_cell(t["task_id"]),
                    md_cell(tracks.get(t["task_id"], "")),
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
        "Per pair of contestants in a configuration, the closest first (the hardest decision):",
        "",
        *_table(
            [
                "config",
                "x",
                "y",
                "tasks",
                "mean difference",
                "discordance",
                "tasks for 5 points",
                "tasks for 10 points",
                "tasks for 15 points",
                "a month for the two at 15 points (USD)",
            ],
            [
                [
                    md_cell(p["config"]),
                    md_cell(p["x"]),
                    md_cell(p["y"]),
                    str(p["tasks"]),
                    f"{p['mean_difference']:+.2f}",
                    _n(p["discordance"], 2),
                    _n(p["tasks_needed"]["5"]),
                    _n(p["tasks_needed"]["10"]),
                    _n(p["tasks_needed"]["15"]),
                    _n(p["est_cost_usd"], 2),
                ]
                for p in grade.get("pairs") or []
            ]
            or [["—"] * 10],
        ),  # fmt: skip
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
        "## Attempts per contestant",
        "",
        *(
            [f"Reduced before the run (step {data['reduction']['applied_step']}):", ""]
            + [f"- {md_cell(str(s['why']))}" for s in data["reduction"]["applied"]]
            + [""]
            if data["reduction"]["applied"]
            else ["No reduction applied: every contestant got the planned attempts.", ""]
        ),
        *_table(
            ["config", *[md_cell(m) for m in next(iter(data["reduction"]["k"].values()), {})]],
            [[md_cell(c), *[str(k) for k in ks.values()]] for c, ks in data["reduction"]["k"].items()],
        ),
        "",
        *(
            [
                "## Voided attempts",
                "",
                "Recorded, paid for, and left out of every figure above; run again after the fix.",
                "",
            ]
            + [f"- {v['count']}: {md_cell(str(v['reason']))}" for v in data.get("voided", [])]
            + [""]
            if data.get("voided")
            else []
        ),
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
    rows = [r for r in read_jsonl(ledger_path) if r.get("kind") in ("attempt", "void")]
    data = results(rows, plan, ledger_bytes=raw, cassettes=cassettes)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_bytes(
        (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    )
    (out / "results.md").write_bytes(to_markdown(data).encode("utf-8"))
    return data
