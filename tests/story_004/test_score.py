"""STORY-004 T2: the pure scorer, against the numbers in stories/STORY-004.cases.yaml.

Cases S4-09, S4-10, S4-13, S4-14, S4-15 (aggregation) and S4-19 are read from the YAML where the file
gives data; the rules the spec leaves open (which outcomes count as attempts, what a cell's cost
includes, when a task is saturated, the edges of the statistics) each have a test of their own below.

Per-task pass rates in the cases file are `passes / 3` written to four decimals (the file header fixes
k = 3), so `as_k3` turns them back into exact thirds before they reach the scorer.
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.bench_score import (
    by_contestant,
    cells,
    cost_per_pass,
    memo,
    paired_delta,
    pass_hat_k,
    percentile,
    ranking_statement,
    saturated,
    score,
    t_critical,
    task_clustered,
    tasks_needed,
    wilson,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = {c["id"]: c for c in yaml.safe_load((ROOT / "stories" / "STORY-004.cases.yaml").read_text("utf-8"))}
K = 3
EFFORT = "high"


def as_k3(rate: float) -> float:
    return round(rate * K) / K


def outcomes_for(rate: float) -> list[str]:
    passes = round(rate * K)
    return ["pass"] * passes + ["fail"] * (K - passes)


def attempt_rows(
    task: str,
    config: str,
    model: str,
    outcomes: list[str],
    *,
    sha: str | None = None,
    cost: float | None = 0.01,
    latency: float = 1.0,
    failed_checks: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for i, outcome in enumerate(outcomes, start=1):
        rows.append(
            {
                "kind": "attempt",
                "task_id": task,
                "task_sha256": sha or f"sha-{task}",
                "family": "domain",
                "config": config,
                "contestant": {"model": model, "effort": EFFORT, "harness": "h", "harness_version": "1"},
                "attempt": i,
                "outcome": outcome,
                "calls": [],
                "cost_usd": cost,
                "cost_basis": "measured-usage" if cost is not None else "unpriced",
                "latency_s": latency,
                "wall_s": latency,
                "grader": {"name": "g", "failed_checks": list(failed_checks or []) if outcome == "fail" else []},
                "judge": None,
                "at": f"2026-10-11T00:00:{i:02d}Z",
            }
        )
    return rows


def ledger_rows(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in ledger:
        rows += attempt_rows(
            entry["task"], entry["config"], entry["model"], entry["outcomes"], sha=entry.get("task_sha256")
        )
    return rows


def close(actual: float | None, expected: float, places: int = 4) -> bool:
    return actual is not None and round(actual, places) == round(expected, places)


def cell_for(cs: list[dict[str, Any]], task: str, model: str, config: str = "B") -> dict[str, Any]:
    (found,) = [c for c in cs if c["task_id"] == task and c["model"] == model and c["config"] == config]
    return found


# ---------------------------------------------------------------- S4-13: the statistics, by hand


@pytest.mark.parametrize("row", [r for r in CASES["S4-13"]["rows"] if "passes" in r and "attempts" in r])
def test_s4_13_wilson_pass_hat_any_pass(row: dict[str, Any]) -> None:
    expected = row["expected"]
    lo, hi = wilson(row["passes"], row["attempts"])
    assert close(lo, expected["wilson_95"][0]) and close(hi, expected["wilson_95"][1]), (lo, hi)
    for key, value in expected.items():
        if key.startswith("pass_hat_"):
            k = int(key.removeprefix("pass_hat_"))
            assert close(pass_hat_k(row["attempts"], row["passes"], k), value), key
    if "any_pass" in expected:
        assert (row["passes"] > 0) is expected["any_pass"]


@pytest.mark.parametrize("row", [r for r in CASES["S4-13"]["rows"] if "task_pass_rates" in r])
def test_s4_13_task_clustered_t_interval(row: dict[str, Any]) -> None:
    mean, lo, hi = task_clustered([as_k3(r) for r in row["task_pass_rates"]])
    assert close(mean, row["expected"]["mean"])
    assert close(lo, row["expected"]["task_clustered_95"][0]) and close(hi, row["expected"]["task_clustered_95"][1])


def test_s4_13_t_critical_values_the_file_states() -> None:
    assert t_critical(5) == 2.5706 and t_critical(6) == 2.4469


def test_s4_13_latency_median_and_p95_by_nearest_rank() -> None:
    (row,) = [r for r in CASES["S4-13"]["rows"] if "latencies_s" in r]
    assert percentile(row["latencies_s"], 0.5) == row["expected"]["median"]
    assert percentile(row["latencies_s"], 0.95) == row["expected"]["p95"]


@pytest.mark.parametrize("row", [r for r in CASES["S4-13"]["rows"] if "cost_usd_total" in r])
def test_s4_13_cost_per_pass(row: dict[str, Any]) -> None:
    got = cost_per_pass(row["cost_usd_total"], row["passes"])
    expected = row["expected"]["cost_per_pass"]
    assert got is None if expected is None else close(got, expected)


# ---------------------------------------------------------------- S4-09: saturation flags, never removes


def test_s4_09_saturated_task_is_flagged_and_listed_and_stays_in_the_average() -> None:
    case = CASES["S4-09"]
    rows = ledger_rows(case["ledger"])
    cs = cells(rows)
    for task, flag in case["expected"]["saturated"].items():
        assert all(c["saturated"] is flag for c in cs if c["task_id"] == task), task
    assert saturated(cs, "B") == {("KB-03", "sha-KB-03")}
    m = memo(cs, rows, {})
    assert [(c["task_id"], c["config"]) for c in m["commodity"]] == [
        (e["task_id"], e["config"]) for e in case["expected"]["commodity"]
    ]
    rates = {b["model"]: b["mean_task_pass_rate"] for b in by_contestant(cs, rows)}
    for model, expected in case["expected"]["mean_task_pass_rate"].items():
        assert close(rates[model], expected), (model, rates[model])


def test_s4_09_commodity_names_the_cheapest_passing_contestant() -> None:
    rows = attempt_rows("KB-03", "B", "m1", ["pass"] * 3, cost=0.03) + attempt_rows(
        "KB-03", "B", "m2", ["pass"] * 3, cost=0.01
    )
    (entry,) = memo(cells(rows), rows, {})["commodity"]
    assert entry["cheapest_passing_model"] == "m2" and close(entry["cost_per_pass"], 0.01)


def test_saturation_needs_every_contestant_of_the_configuration() -> None:
    # m2 ran in B but never ran KB-03: KB-03 is not saturated in B, however well m1 did.
    rows = attempt_rows("KB-03", "B", "m1", ["pass"] * 3) + attempt_rows("KB-04", "B", "m2", ["pass"] * 3)
    cs = cells(rows)
    assert ("KB-03", "sha-KB-03") not in saturated(cs, "B")
    # a contestant in another configuration does not count
    rows += attempt_rows("KB-04", "A", "m1", ["fail"] * 3)
    assert ("KB-04", "sha-KB-04") not in saturated(cells(rows), "B")  # m1 never ran KB-04 in B
    assert saturated(cells(rows), "A") == set()


# ---------------------------------------------------------------- S4-10: no ranking, ordered by name


@pytest.mark.parametrize("row", CASES["S4-10"]["rows"])
def test_s4_10_ranking_statement(row: dict[str, Any]) -> None:
    assert ranking_statement(row["tasks"]) == row["expected"]["ranking"]


def test_s4_10_above_eight_tasks_still_no_ranking_rule() -> None:
    assert ranking_statement(9).startswith("none:")


def test_s4_10_contestants_ordered_by_name_with_task_clustered_intervals() -> None:
    rows = ledger_rows(CASES["S4-09"]["ledger"])
    random.Random(4).shuffle(rows)
    result = score(rows, {}, benchmark="keysbench-2026.10")
    names = [(b["config"], b["model"], b["effort"]) for b in result["by_contestant"]]
    assert names == sorted(names)
    m1 = next(b for b in result["by_contestant"] if b["model"] == "m1")
    assert m1["task_clustered_95"] == list(task_clustered([1.0, 2 / 3])[1:])
    assert result["ranking"] == "none: n <= 8 tasks" and result["tasks"] == 2


# ---------------------------------------------------------------- S4-14: paired deltas per model


def test_s4_14_paired_delta_a0_minus_b() -> None:
    case = CASES["S4-14"]
    a0 = {f"KB-0{i + 1}": as_k3(r) for i, r in enumerate(case["per_task_pass_rates"]["A0"])}
    b = {f"KB-0{i + 1}": as_k3(r) for i, r in enumerate(case["per_task_pass_rates"]["B"])}
    (exp,) = case["expected"]["deltas"]
    mean, lo, hi, n = paired_delta(a0, b)
    assert close(mean, exp["mean_paired_difference"]) and n == exp["tasks"]
    assert close(lo, exp["task_clustered_95"][0]) and close(hi, exp["task_clustered_95"][1])


def test_s4_14_score_reports_both_deltas_per_model_over_shared_tasks() -> None:
    case = CASES["S4-14"]
    rows: list[dict[str, Any]] = []
    for config, rates in case["per_task_pass_rates"].items():
        for i, r in enumerate(rates):
            rows += attempt_rows(f"KB-0{i + 1}", config, "m1", outcomes_for(r))
    rows += attempt_rows("KB-01", "A", "m1", ["pass"] * 3)  # A ran one task only: A - A0 pairs over that one
    result = score(rows, {}, benchmark="keysbench-2026.10")
    by_kind = {d["kind"]: d for d in result["deltas"]}
    (exp,) = case["expected"]["deltas"]
    a0b = by_kind["A0-B"]
    assert a0b["model"] == exp["model"] and a0b["tasks"] == exp["tasks"]
    assert close(a0b["mean_paired_difference"], exp["mean_paired_difference"])
    assert [round(x, 4) for x in a0b["task_clustered_95"]] == exp["task_clustered_95"]
    assert by_kind["A-A0"]["tasks"] == 1 and close(by_kind["A-A0"]["mean_paired_difference"], 0.0)


def test_s4_14_paired_delta_pairs_only_tasks_both_ran() -> None:
    mean, _, _, n = paired_delta({"KB-01": 1.0, "KB-02": 0.0}, {"KB-01": 0.0, "KB-03": 1.0})
    assert n == 1 and mean == 1.0
    assert paired_delta({"KB-01": 1.0}, {"KB-02": 1.0}) is None


# ---------------------------------------------------------------- S4-15: digests are never mixed


def test_s4_15_rows_from_different_digests_are_different_cells() -> None:
    case = CASES["S4-15"]
    cs = cells(ledger_rows(case["ledger"]))
    kb03_m1 = [c for c in cs if c["task_id"] == "KB-03" and c["model"] == "m1"]
    assert len(kb03_m1) == case["expected"]["cells_for_KB-03_m1"]
    assert {(c["task_sha256"], c["passes"], c["attempts"]) for c in kb03_m1} == {("aaa", 1, 1), ("bbb", 0, 1)}


# ---------------------------------------------------------------- S4-19: the decision memo

FAILURE_NAMES = {"KB-03": {"kb03.reads_before_init": "reads before INIT"}}


def s4_19_rows() -> list[dict[str, Any]]:
    # "samples of S4-09 + one failing attempt with failed_checks [kb03.reads_before_init]". The extra
    # attempt cannot sit in B/m1 or B/m2 without breaking S4-09's own expectations (KB-03 saturated in B,
    # m1 0.8333, m2 0.6667), so it is a single A0 attempt of m1.
    return ledger_rows(CASES["S4-09"]["ledger"]) + attempt_rows(
        "KB-03", "A0", "m1", ["fail"], failed_checks=["kb03.reads_before_init"]
    )


def test_s4_19_memo_sections_and_failure_mode() -> None:
    case = CASES["S4-19"]
    rows = s4_19_rows()
    m = memo(cells(rows), rows, FAILURE_NAMES)
    assert list(m) == case["expected"]["memo_sections"]
    want = case["expected"]["failure_modes_contains"]
    (mode,) = [f for f in m["failure_modes"] if f["mode"] == want["mode"]]
    assert mode["count"] == want["count"]
    assert (mode["task_id"], mode["config"], mode["model"]) == ("KB-03", "A0", "m1")
    # S4-09 still holds on this ledger
    assert [(c["task_id"], c["config"]) for c in m["commodity"]] == [("KB-03", "B")]


def test_s4_19_tasks_needed_for_15_points_at_the_case_discordance() -> None:
    # n = (1.959964*sqrt(0.3) + 0.841621*sqrt(0.3 - 0.0225))^2 / 0.0225
    #   = (1.073520 + 0.443352)^2 / 0.0225 = 2.300901 / 0.0225 = 102.26 -> 103
    expected = CASES["S4-19"]["expected"]["sample_size_formula"]
    assert tasks_needed(expected["discordance_rate"], 0.15) == expected["tasks_needed_for_15_points"]


def test_s4_19_discordance_measured_from_the_ledger() -> None:
    # Discordance is measured within each configuration, over every pair of its contestants and every
    # task both ran: d_t = p_x (1 - p_y) + p_y (1 - p_x), the probability that one attempt of each
    # disagrees. On this ledger only B has a pair (m1, m2):
    #   KB-03: 1 * 0 + 1 * 0 = 0;  KB-04: 2/3 * 2/3 + 1/3 * 1/3 = 5/9;  mean = 5/18 = 0.2778
    #   n = (1.959964*sqrt(5/18) + 0.841621*sqrt(5/18 - 0.0225))^2 / 0.0225 = 94.51 -> 95
    expected = CASES["S4-19"]["expected"]["decision_grade"]
    rows = s4_19_rows()
    grade = memo(cells(rows), rows, FAILURE_NAMES)["decision_grade"]
    assert close(grade["discordance_rate"], 5 / 18) and close(grade["discordance_rate"], expected["discordance_rate"])
    assert grade["tasks_needed_for_15_points"] == expected["tasks_needed_for_15_points"]
    # 13 attempts (12 from S4-09 + the A0 one) at 0.01 = 0.13 over 2 task digests = 0.065 per task
    assert close(grade["est_cost_usd"], 95 * 0.065)


def test_s4_19_unpriced_attempt_makes_the_estimate_null() -> None:
    rows = s4_19_rows()
    rows[0]["cost_usd"] = None
    grade = memo(cells(rows), rows, FAILURE_NAMES)["decision_grade"]
    assert grade["est_cost_usd"] is None and grade["tasks_needed_for_15_points"] == 95


def test_decision_grade_without_a_pair_of_contestants() -> None:
    rows = attempt_rows("KB-03", "B", "m1", ["pass", "fail", "pass"])
    grade = memo(cells(rows), rows, {})["decision_grade"]
    assert grade["discordance_rate"] is None and grade["tasks_needed_for_15_points"] is None
    assert grade["est_cost_usd"] is None and "pair" in grade["note"]


def test_unnamed_failed_check_keeps_its_id() -> None:
    rows = attempt_rows("KB-04", "B", "m1", ["fail"], failed_checks=["kb04.rss"])
    (mode,) = memo(cells(rows), rows, FAILURE_NAMES)["failure_modes"]
    assert mode["mode"] == "kb04.rss"


# ---------------------------------------------------------------- outcomes: what counts as an attempt


def test_named_outcomes_and_what_counts_as_an_attempt() -> None:
    outcomes = ["pass", "fail", "refused", "truncated", "invalid", "error", "budget_stopped"]
    rows = attempt_rows("KB-03", "B", "m1", outcomes, cost=0.10)
    rows[-1]["latency_s"] = 99.0  # a stopped attempt's partial latency must not reach the percentiles
    (cell,) = cells(rows)
    assert cell["attempts"] == 5  # pass, fail, refused, truncated, invalid
    assert cell["passes"] == 1
    assert (cell["refused"], cell["truncated"], cell["invalid"]) == (1, 1, 1)
    assert (cell["errors"], cell["budget_stopped"]) == (1, 1)
    assert close(cell["cost_usd_total"], 0.70)  # every row's spend, stopped and errored included (DR-11)
    assert close(cell["cost_per_pass"], 0.70)
    assert cell["latency_p95_s"] == 1.0


def test_a_cell_with_only_stopped_attempts_stays_out_of_rates() -> None:
    rows = attempt_rows("KB-03", "B", "m1", ["pass"] * 3) + attempt_rows("KB-04", "B", "m1", ["budget_stopped"])
    cs = cells(rows)
    stopped = cell_for(cs, "KB-04", "m1")
    assert stopped["attempts"] == 0 and stopped["wilson_95"] == [0.0, 1.0] and stopped["latency_median_s"] is None
    (b,) = by_contestant(cs, rows)
    assert b["mean_task_pass_rate"] == 1.0 and b["tasks"] == 1


def test_unknown_outcome_is_refused() -> None:
    rows = attempt_rows("KB-03", "B", "m1", ["maybe"])
    with pytest.raises(ValueError, match="outcome"):
        cells(rows)


def test_non_attempt_lines_are_ignored() -> None:
    rows = attempt_rows("KB-03", "B", "m1", ["pass"]) + [{"kind": "run", "budget_usd": 60}]
    assert len(cells(rows)) == 1


# ---------------------------------------------------------------- edges of the statistics


def test_wilson_with_no_attempts_is_the_whole_interval() -> None:
    assert wilson(0, 0) == (0.0, 1.0)


def test_pass_hat_k_below_k_passes_is_zero_and_k_above_n_is_refused() -> None:
    assert pass_hat_k(3, 1, 2) == 0.0
    with pytest.raises(ValueError):
        pass_hat_k(3, 3, 4)


def test_task_clustered_with_one_task_is_the_whole_range() -> None:
    assert task_clustered([0.6]) == (0.6, 0.0, 1.0)
    with pytest.raises(ValueError):
        task_clustered([])


def test_t_critical_beyond_the_table_is_the_conservative_df30_value() -> None:
    assert t_critical(1) == 12.7062 and t_critical(30) == 2.0423 and t_critical(200) == 2.0423
    with pytest.raises(ValueError):
        t_critical(0)


def test_percentile_nearest_rank_takes_the_lower_middle_on_even_n() -> None:
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.5) == 2.0
    assert percentile([5.0], 0.95) == 5.0
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_tasks_needed_is_null_when_15_points_cannot_exist() -> None:
    # |p10 - p01| <= p10 + p01 = d: below 0.15 discordance a 15-point difference is impossible
    assert tasks_needed(0.10, 0.15) is None
    assert tasks_needed(1.0, 0.15) == math.ceil((1.959964 + 0.841621 * math.sqrt(1 - 0.0225)) ** 2 / 0.0225)


def test_score_is_deterministic_and_order_free() -> None:
    rows = s4_19_rows()
    rng = random.Random(19)
    for row in rows:  # costs that do not add up the same in every order (0.1 + 0.2 + 0.3 != 0.3 + 0.2 + 0.1)
        row["cost_usd"] = rng.choice([0.1, 0.2, 0.3, 0.7, 1e-3, 1e-17])
        row["latency_s"] = rng.uniform(0.5, 9.0)
    first = score(rows, FAILURE_NAMES, benchmark="keysbench-2026.10")
    for seed in range(20):
        shuffled = list(rows)
        random.Random(seed).shuffle(shuffled)
        assert score(shuffled, FAILURE_NAMES, benchmark="keysbench-2026.10") == first, seed
    assert set(first) == {"benchmark", "tasks", "ranking", "memo", "cells", "by_contestant", "deltas"}
    assert first["benchmark"] == "keysbench-2026.10"
