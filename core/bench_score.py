"""KeysBench scorer (STORY-004): attempt lines in, the results as plain data out. Pure and deterministic.

No model, no network, no clock: the same ledger rows give the same dict in any order. The CLI adds
what is not a function of the rows (`generated_at`, `prices_checked_on`, input digests, `not_run`).

The unit is a cell, `(task_id, task_sha256, config, model, effort)` (DR-1, DR-13): rows of the same task
under two digests are two cells, and two tasks wherever tasks are counted or paired.

What counts as an attempt (DR-5, DR-11), the rule every number below rests on:
- `pass` is an attempt that passed; `fail`, `refused`, `truncated` and `invalid` are attempts that did
  not. The last three are reported apart (`refused`, `truncated`, `invalid` on the cell), never as `fail`.
- `budget_stopped` and `error` are not attempts: the first was never allowed to finish, the second is a
  failure of the harness, not an observation of the contestant. Both are counted apart on the cell.
- Cost includes every row of the cell, stopped and errored ones too: what was spent was spent (DR-11).
  Latency percentiles use the counted attempts only, since a stopped attempt's latency is partial.
- A cell with no counted attempt has no pass rate: it stays out of every average and paired difference.

Statistics:
- Wilson 95 % per cell only (z = 1.959964); with no attempts the interval is [0, 1].
- Intervals across tasks are t intervals over per-task pass rates (the task is the independent unit,
  DR-10), df = tasks - 1, two-sided 95 %, clipped to the range of the quantity. One task gives the whole
  range. Beyond df 30 the df 30 value is used, which is wider than the true one (conservative).
- Percentiles are nearest rank: the value at rank ceil(q * n). The median of an even count is therefore
  the lower middle value, not the average of the two.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from itertools import combinations
from statistics import NormalDist, fmean, stdev
from typing import Any, TypeVar

JSONObject = dict[str, Any]
TaskKey = tuple[str, str]
CellKey = tuple[str, str, str, str, str]
Contestant = tuple[str, str, str]
K = TypeVar("K", bound=Hashable)

PASSED = "pass"
NOT_PASSED = frozenset({"fail", "refused", "truncated", "invalid"})
NOT_ATTEMPTS = frozenset({"budget_stopped", "error"})
OUTCOMES = NOT_PASSED | NOT_ATTEMPTS | {PASSED}

Z95 = 1.959964
DELTA_POINTS = 0.15
ALPHA = 0.05
POWER = 0.8
NO_RANKING_UP_TO = 8
# A0 - B: what the product scaffold adds to the API loop; A - A0: what running code adds; A - B: the
# product as shipped against the API loop, the comparison a buyer of either actually faces.
DELTA_KINDS = (("A-A0", "A", "A0"), ("A0-B", "A0", "B"), ("A-B", "A", "B"))
PAIR_POINTS = (0.05, 0.10, 0.15)

# Two-sided 95 % critical values of Student's t (0.975 quantile), df 1..30, four decimals. The standard
# library has no t distribution; these were checked against a numerical integration of the t density.
T95 = {
    1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706, 6: 2.4469, 7: 2.3646, 8: 2.3060,
    9: 2.2622, 10: 2.2281, 11: 2.2010, 12: 2.1788, 13: 2.1604, 14: 2.1448, 15: 2.1314, 16: 2.1199,
    17: 2.1098, 18: 2.1009, 19: 2.0930, 20: 2.0860, 21: 2.0796, 22: 2.0739, 23: 2.0687, 24: 2.0639,
    25: 2.0595, 26: 2.0555, 27: 2.0518, 28: 2.0484, 29: 2.0452, 30: 2.0423,
}  # fmt: skip


# ---------------------------------------------------------------- primitives


def wilson(passes: int, n: int) -> tuple[float, float]:
    """Wilson score interval, 95 %. No attempts: the whole interval."""
    if n == 0:
        return (0.0, 1.0)
    if not 0 <= passes <= n:
        raise ValueError(f"passes {passes} outside 0..{n}")
    p = passes / n
    z2 = Z95 * Z95
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k: the probability that k attempts drawn from the n recorded all pass, C(c, k) / C(n, k)."""
    if not 1 <= k <= n or not 0 <= c <= n:
        raise ValueError(f"pass^k needs 1 <= k <= n and 0 <= c <= n, got n={n} c={c} k={k}")
    return math.comb(c, k) / math.comb(n, k)


def any_pass(passes: int) -> bool:
    return passes > 0


def cost_per_pass(cost_usd_total: float | None, passes: int) -> float | None:
    """Total cost over passes; null when nothing passed or any part of the cost is unpriced."""
    if cost_usd_total is None or passes == 0:
        return None
    return cost_usd_total / passes


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest rank: the value at rank ceil(q * n), at least the first."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def t_critical(df: int) -> float:
    if df < 1:
        raise ValueError(f"t interval needs df >= 1, got {df}")
    return T95[min(df, 30)]


def task_clustered(rates: Sequence[float], low: float = 0.0, high: float = 1.0) -> tuple[float, float, float]:
    """Mean of per-task values and its t interval (df = tasks - 1), clipped to [low, high]."""
    if not rates:
        raise ValueError("task-clustered interval of no tasks")
    mean = fmean(rates)
    if len(rates) == 1:
        return (mean, low, high)
    half = t_critical(len(rates) - 1) * stdev(rates) / math.sqrt(len(rates))
    return (mean, max(low, mean - half), min(high, mean + half))


def paired_delta(rates_x: Mapping[K, float], rates_y: Mapping[K, float]) -> tuple[float, float, float, int] | None:
    """Per-task differences x - y over the tasks both ran: mean, task-clustered interval, task count."""
    diffs = [rates_x[t] - rates_y[t] for t in rates_x if t in rates_y]
    if not diffs:
        return None
    mean, lo, hi = task_clustered(diffs, -1.0, 1.0)
    return (mean, lo, hi, len(diffs))


def tasks_needed(
    discordance: float, delta: float = DELTA_POINTS, alpha: float = ALPHA, power: float = POWER
) -> int | None:
    """Paired tasks needed to detect a difference of `delta` in pass rate (McNemar, Connor 1987).

    n = (z_{alpha/2} sqrt(d) + z_beta sqrt(d - delta^2))^2 / delta^2, rounded up. Null when d < delta:
    a difference is at most the discordance (|p10 - p01| <= p10 + p01), so it cannot occur at all.
    """
    if discordance < delta:
        return None
    z_a = NormalDist().inv_cdf(1 - alpha / 2)
    z_b = NormalDist().inv_cdf(power)
    n = (z_a * math.sqrt(discordance) + z_b * math.sqrt(discordance - delta * delta)) ** 2 / (delta * delta)
    return math.ceil(n)


def ranking_statement(n_tasks: int) -> str:
    """DR-10. Above eight tasks the spec defines no ranking rule either, and this scorer computes none."""
    if n_tasks <= NO_RANKING_UP_TO:
        return f"none: n <= {NO_RANKING_UP_TO} tasks"
    return f"none: no ranking rule is defined for {n_tasks} tasks"


# ---------------------------------------------------------------- ledger rows


def _attempt_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    out = []
    for row in rows:
        if row.get("kind") != "attempt":
            continue
        if row.get("outcome") not in OUTCOMES:
            raise ValueError(
                f"unknown outcome {row.get('outcome')!r} on {row.get('task_id')!r} attempt {row.get('attempt')!r}"
            )
        out.append(row)
    return out


def _cell_key(row: Mapping[str, Any]) -> CellKey:
    try:
        contestant = row["contestant"]
        return (row["task_id"], row["task_sha256"], row["config"], contestant["model"], contestant["effort"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"attempt line without {exc}: every row names task, digest, config, model and effort") from exc


def _counted(row: Mapping[str, Any]) -> bool:
    return row["outcome"] not in NOT_ATTEMPTS


def _cost(rows: Iterable[Mapping[str, Any]]) -> float | None:
    costs = [row.get("cost_usd") for row in rows]
    if any(c is None for c in costs):
        return None
    # fsum is exactly rounded, so the total does not depend on the order of the ledger lines
    return math.fsum(float(c) for c in costs if c is not None)


def _latencies(rows: Iterable[Mapping[str, Any]]) -> list[float]:
    return [float(r["latency_s"]) for r in rows if _counted(r)]


def _rate(cell: Mapping[str, Any]) -> float:
    return float(cell["passes"]) / float(cell["attempts"])


def _task(cell: Mapping[str, Any]) -> TaskKey:
    return (cell["task_id"], cell["task_sha256"])


def _contestant(cell: Mapping[str, Any]) -> Contestant:
    return (cell["config"], cell["model"], cell["effort"])


# ---------------------------------------------------------------- cells and contestants


def cells(rows: Iterable[Mapping[str, Any]]) -> list[JSONObject]:
    """One entry per (task_id, task_sha256, config, model, effort), ordered by that key."""
    groups: dict[CellKey, list[Mapping[str, Any]]] = {}
    for row in _attempt_rows(rows):
        groups.setdefault(_cell_key(row), []).append(row)
    out: list[JSONObject] = []
    for key in sorted(groups):
        group = groups[key]
        outcomes = Counter(r["outcome"] for r in group)
        attempts = sum(n for o, n in outcomes.items() if o not in NOT_ATTEMPTS)
        passes = outcomes[PASSED]
        total = _cost(group)
        lat = _latencies(group)
        task_id, sha, config, model, effort = key
        out.append(
            {
                "task_id": task_id,
                "task_sha256": sha,
                "config": config,
                "model": model,
                "effort": effort,
                "attempts": attempts,
                "passes": passes,
                "wilson_95": list(wilson(passes, attempts)),
                "pass_hat_k": {str(k): pass_hat_k(attempts, passes, k) for k in range(1, attempts + 1)},
                "any_pass": any_pass(passes),
                "cost_usd_total": total,
                "cost_per_pass": cost_per_pass(total, passes),
                "latency_median_s": percentile(lat, 0.5) if lat else None,
                "latency_p95_s": percentile(lat, 0.95) if lat else None,
                "saturated": False,
                "invalid": outcomes["invalid"],
                "refused": outcomes["refused"],
                "truncated": outcomes["truncated"],
                "errors": outcomes["error"],
                "budget_stopped": outcomes["budget_stopped"],
            }
        )
    for config in sorted({c["config"] for c in out}):
        flagged = saturated(out, config)
        for c in out:
            if c["config"] == config and _task(c) in flagged:
                c["saturated"] = True
    return out


def saturated(cell_list: Sequence[Mapping[str, Any]], config: str) -> set[TaskKey]:
    """Tasks that every contestant of `config` ran and passed on every counted attempt (DR-9).

    A contestant of the configuration that did not run the task (or has no counted attempt on it) keeps
    it unsaturated. This only flags: nothing is ever removed from an average because of it.
    """
    in_config = [c for c in cell_list if c["config"] == config]
    everyone = {(c["model"], c["effort"]) for c in in_config}
    perfect: dict[TaskKey, set[tuple[str, str]]] = {}
    for c in in_config:
        if c["attempts"] > 0 and c["passes"] == c["attempts"]:
            perfect.setdefault(_task(c), set()).add((c["model"], c["effort"]))
    return {task for task, who in perfect.items() if who == everyone}


def _rates_by_contestant(cell_list: Sequence[Mapping[str, Any]]) -> dict[Contestant, dict[TaskKey, float]]:
    rates: dict[Contestant, dict[TaskKey, float]] = {}
    for c in cell_list:
        if c["attempts"] > 0:
            rates.setdefault(_contestant(c), {})[_task(c)] = _rate(c)
    return rates


def by_contestant(cell_list: Sequence[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]]) -> list[JSONObject]:
    """Per (config, model, effort), ordered by that triple: mean task pass rate with its task-clustered
    interval, cost per pass over all its tasks, and latency median and p95 over its counted attempts."""
    rates = _rates_by_contestant(cell_list)
    rows_of: dict[Contestant, list[Mapping[str, Any]]] = {}
    for row in _attempt_rows(rows):
        key = _cell_key(row)
        rows_of.setdefault((key[2], key[3], key[4]), []).append(row)
    out: list[JSONObject] = []
    for who in sorted({_contestant(c) for c in cell_list}):
        mine = [c for c in cell_list if _contestant(c) == who]
        task_rates = list(rates.get(who, {}).values())
        interval = task_clustered(task_rates) if task_rates else None
        lat = _latencies(rows_of.get(who, []))
        total = _cost(rows_of.get(who, []))
        out.append(
            {
                "config": who[0],
                "model": who[1],
                "effort": who[2],
                "tasks": len(task_rates),
                "mean_task_pass_rate": None if interval is None else interval[0],
                "task_clustered_95": None if interval is None else [interval[1], interval[2]],
                "cost_per_pass": cost_per_pass(total, sum(int(c["passes"]) for c in mine)),
                "latency_median_s": percentile(lat, 0.5) if lat else None,
                "latency_p95_s": percentile(lat, 0.95) if lat else None,
            }
        )
    return out


def deltas(cell_list: Sequence[Mapping[str, Any]]) -> list[JSONObject]:
    """A0 - B (what the product scaffold adds) and A - A0 (what running code adds), per model and effort,
    as paired differences over the tasks both configurations ran (DR-9: saturated tasks included)."""
    rates = _rates_by_contestant(cell_list)
    out: list[JSONObject] = []
    for model, effort in sorted({(c["model"], c["effort"]) for c in cell_list}):
        for kind, x, y in DELTA_KINDS:
            pd = paired_delta(rates.get((x, model, effort), {}), rates.get((y, model, effort), {}))
            if pd is None:
                continue
            mean, lo, hi, n = pd
            out.append(
                {
                    "model": model,
                    "effort": effort,
                    "kind": kind,
                    "mean_paired_difference": mean,
                    "task_clustered_95": [lo, hi],
                    "tasks": n,
                }
            )
    return out


# ---------------------------------------------------------------- decision memo


def _commodity(cell_list: Sequence[Mapping[str, Any]]) -> list[JSONObject]:
    out: list[JSONObject] = []
    for config in sorted({c["config"] for c in cell_list}):
        for task in sorted(saturated(cell_list, config)):
            candidates = [c for c in cell_list if c["config"] == config and _task(c) == task]
            best = min(
                candidates,
                key=lambda c: (c["cost_per_pass"] is None, c["cost_per_pass"] or 0.0, c["model"], c["effort"]),
            )
            out.append(
                {
                    "task_id": task[0],
                    "task_sha256": task[1],
                    "config": config,
                    "cheapest_passing_model": best["model"],
                    "effort": best["effort"],
                    "cost_per_pass": best["cost_per_pass"],
                }
            )
    return out


def _failure_modes(rows: Sequence[Mapping[str, Any]], names: Mapping[str, Mapping[str, str]]) -> list[JSONObject]:
    """Failed check ids of `fail` attempts, named by the task that declares them; an undeclared id keeps
    its id as the name, so no failure disappears for lack of a label."""
    counts: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for row in rows:
        if row["outcome"] != "fail":
            continue
        task_id, sha, config, model, effort = _cell_key(row)
        checks = (row.get("grader") or {}).get("failed_checks") or []
        for check in sorted(set(checks)):
            mode = names.get(task_id, {}).get(check, check)
            counts[(task_id, sha, config, model, effort, mode)] += 1
    return [
        {"mode": k[5], "task_id": k[0], "task_sha256": k[1], "config": k[2], "model": k[3], "effort": k[4], "count": n}
        for k, n in sorted(counts.items())
    ]


def discordance(cell_list: Sequence[Mapping[str, Any]]) -> tuple[float | None, int]:
    """Measured discordance between contestants, and the number of (pair, task) terms it averages.

    Within each configuration, for every pair of its contestants and every task both ran, the chance that
    one attempt of each disagrees: d_t = p_x (1 - p_y) + p_y (1 - p_x), with p the cell pass rate. The
    rate is the mean of those terms. Configurations are not paired with each other here; that comparison
    is the deltas.
    """
    rates = _rates_by_contestant(cell_list)
    terms: list[float] = []
    for config in sorted({c[0] for c in rates}):
        members = sorted(c for c in rates if c[0] == config)
        for x, y in combinations(members, 2):
            for task, px in rates[x].items():
                if task in rates[y]:
                    py = rates[y][task]
                    terms.append(px * (1 - py) + py * (1 - px))
    return (fmean(terms) if terms else None, len(terms))


def _pairs(cell_list: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> list[JSONObject]:
    """Every pair of contestants in a configuration, closest first (the smallest mean difference over the
    tasks both ran): the pair a decision is hardest to make about. For each, its own discordance, the paired
    tasks a month would need to detect a 5, 10 and 15-point difference, and what that month would cost the
    two of them at this run's measured cost per task (all its attempts on a task). Pooling every pair
    hides the one that matters, and pricing the whole grid overstates the cost of comparing two
    contestants (review lens 2B F3)."""
    rates = _rates_by_contestant(cell_list)
    by: dict[Contestant, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = _cell_key(row)
        by.setdefault((key[2], key[3], key[4]), []).append(row)

    def per_task(who: Contestant) -> float | None:
        total = _cost(by.get(who, []))
        return None if total is None or not rates.get(who) else total / len(rates[who])

    out: list[JSONObject] = []
    for config in sorted({c[0] for c in rates}):
        for x, y in combinations(sorted(c for c in rates if c[0] == config), 2):
            common = [t for t in rates[x] if t in rates[y]]
            if not common:
                continue
            px, py = [rates[x][t] for t in common], [rates[y][t] for t in common]
            d = fmean(a * (1 - b) + b * (1 - a) for a, b in zip(px, py, strict=True))
            needed = {str(round(p * 100)): tasks_needed(d, p) for p in PAIR_POINTS}
            cx, cy, n15 = per_task(x), per_task(y), needed["15"]
            out.append(
                {
                    "config": config,
                    "x": x[1],
                    "y": y[1],
                    "effort": x[2] if x[2] == y[2] else f"{x[2]}/{y[2]}",
                    "tasks": len(common),
                    "mean_difference": fmean(a - b for a, b in zip(px, py, strict=True)),
                    "discordance": d,
                    "tasks_needed": needed,
                    "est_cost_usd": None if n15 is None or cx is None or cy is None else n15 * (cx + cy),
                }
            )
    return sorted(out, key=lambda p: (abs(p["mean_difference"]), p["config"], p["x"], p["y"]))


def _decision_grade(cell_list: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> JSONObject:
    d, pairs = discordance(cell_list)
    n = None if d is None else tasks_needed(d)
    n_tasks = len({_task(c) for c in cell_list})
    total = _cost(rows)
    per_task = None if total is None or n_tasks == 0 else total / n_tasks
    est = None if n is None or per_task is None else n * per_task
    test = f"a {round(DELTA_POINTS * 100)}-point paired difference, alpha {ALPHA} two-sided, power {POWER}"
    if d is None:
        note = "no pair of contestants ran a common task within one configuration: discordance not measured"
    elif n is None:
        note = (
            f"measured discordance {d:.4f} over {pairs} contestant-task pairs is below {DELTA_POINTS}: "
            f"{test} cannot occur"
        )
    else:
        cost = "unpriced" if per_task is None else f"{per_task:.4f} USD per task measured over {n_tasks} tasks"
        note = f"discordance over {pairs} contestant-task pairs within a configuration; {test}; cost at {cost}"
    return {
        "discordance_rate": d,
        "tasks_needed_for_15_points": n,
        "est_cost_usd": est,
        "note": note,
        "pairs": _pairs(cell_list, rows),
    }


def memo(
    cell_list: Sequence[Mapping[str, Any]],
    rows: Iterable[Mapping[str, Any]],
    failure_names: Mapping[str, Mapping[str, str]],
) -> JSONObject:
    """The decision memo, computed from the ledger (S4-19). `failure_names` is {task_id: {check_id: name}},
    the names each task declares, passed in so this module never reads a file."""
    attempt_rows = _attempt_rows(rows)
    return {
        "per_task": [
            {
                "task_id": c["task_id"],
                "task_sha256": c["task_sha256"],
                "config": c["config"],
                "model": c["model"],
                "effort": c["effort"],
                "passes": c["passes"],
                "attempts": c["attempts"],
                "cost_per_pass": c["cost_per_pass"],
                "latency_p95_s": c["latency_p95_s"],
            }
            for c in cell_list
        ],
        "commodity": _commodity(cell_list),
        "failure_modes": _failure_modes(attempt_rows, failure_names),
        "decision_grade": _decision_grade(cell_list, attempt_rows),
    }


def score(
    rows: Iterable[Mapping[str, Any]],
    failure_names: Mapping[str, Mapping[str, str]],
    *,
    benchmark: str,
) -> JSONObject:
    """The results as data: everything in results.json that is a function of the ledger rows."""
    attempt_rows = _attempt_rows(rows)
    cell_list = cells(attempt_rows)
    n_tasks = len({_task(c) for c in cell_list})
    return {
        "benchmark": benchmark,
        "tasks": n_tasks,
        "ranking": ranking_statement(n_tasks),
        "memo": memo(cell_list, attempt_rows, failure_names),
        "cells": cell_list,
        "by_contestant": by_contestant(cell_list, attempt_rows),
        "deltas": deltas(cell_list),
    }
