"""STORY-004 T10: `score` and the report (S4-08, S4-14 not_run, S4-15, S4-16, S4-19 in the report).

`score` reads the ledger and the recordings it names, and writes results.json (raw) and results.md
(the decision memo first, contestant text escaped). It makes no model call and opens no socket.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
from pathlib import Path

import pytest
import yaml

from keysbench import report
from keysbench.runner import Plan

ROOT = Path(__file__).resolve().parents[2]
CASES = {c["id"]: c for c in yaml.safe_load((ROOT / "stories" / "STORY-004.cases.yaml").read_text("utf-8"))}


def plan() -> Plan:
    return Plan(
        label="keysbench-test",
        cap_usd=60.0,
        k=3,
        effort="high",
        models=["m1", "m2"],
        configs=["B"],
        tasks=["KB-03", "KB-04"],
        max_tokens=32000,
        max_steps=12,
        reduction=[
            {"why": "fewer attempts for m2", "decided": True, "limits": [{"model": "m2", "k": 1}]},
            {"why": "a later step, not applied", "decided": True, "limits": [{"k": 1}]},
        ],
        applied_step=1,
        not_run=[
            {
                "contestant": "codex-cli",
                "reason": "not run: pricing it needs per-call usage from an account not set up for this run",
            },
            {
                "contestant": "cursor-agent",
                "reason": "not run: its headless agent reports no per-call usage to price from",
            },
        ],
    )


def row(task, sha, model, outcome, attempt, cost=0.01, failed=None, at="2026-10-11T08:00:00Z"):
    return {
        "kind": "attempt", "task_id": task, "task_sha256": sha, "config": "B",
        "contestant": {"model": model, "effort": "high", "harness": "repo-harness", "harness_version": "1"},
        "attempt": attempt, "outcome": outcome, "cost_usd": cost, "latency_s": 1.0, "at": at,
        "grader": {"name": "pytest", "failed_checks": failed or []}, "judge": None,
    }  # fmt: skip


def ledger(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def sample_rows() -> list[dict]:
    rows = []
    for task, sha in (("KB-03", "a" * 64), ("KB-04", "b" * 64)):
        for model, outcomes in (("m1", ["pass", "pass", "fail"]), ("m2", ["pass", "fail", "fail"])):
            rows += [row(task, sha, model, o, i + 1) for i, o in enumerate(outcomes)]
    return rows


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("score opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_s4_08_scoring_twice_gives_the_same_bytes_without_network(tmp_path, no_network):
    path = ledger(tmp_path, sample_rows())
    report.score_files(path, tmp_path / "r1", plan(), cassettes=tmp_path / "c")
    report.score_files(path, tmp_path / "r2", plan(), cassettes=tmp_path / "c")
    for name in ("results.json", "results.md"):
        assert (tmp_path / "r1" / name).read_bytes() == (tmp_path / "r2" / name).read_bytes()


def test_s4_15_results_record_the_digests_they_were_scored_from(tmp_path):
    rows = sample_rows()
    path = ledger(tmp_path, rows)
    cassettes = tmp_path / "c"
    rec = cassettes / "KB-03" / ("a" * 12) / "B-m1-high-1.jsonl"
    rec.parent.mkdir(parents=True)
    rec.write_text('{"key": "x", "response": {}}\n', encoding="utf-8")
    data = report.results(rows, plan(), ledger_bytes=path.read_bytes(), cassettes=cassettes)
    assert data["inputs"]["ledger_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert data["inputs"]["recordings_sha256"] == {
        "KB-03/aaaaaaaaaaaa/B-m1-high-1.jsonl": hashlib.sha256(rec.read_bytes()).hexdigest()
    }


def test_s4_15_two_digests_of_one_task_are_two_cells(tmp_path):
    case = CASES["S4-15"]
    rows = [
        row(r["task"], r["task_sha256"], r["model"], o, i + 1)
        for r in case["ledger"]
        for i, o in enumerate(r["outcomes"])
    ]
    data = report.results(rows, plan(), ledger_bytes=b"", cassettes=tmp_path)
    assert (
        len([c for c in data["cells"] if c["task_id"] == "KB-03" and c["model"] == "m1"])
        == case["expected"]["cells_for_KB-03_m1"]
    )


def test_s4_14_not_run_contestants_are_listed_with_their_reason(tmp_path):
    data = report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path)
    assert [n["contestant"] for n in data["not_run"]] == CASES["S4-14"]["expected"]["not_run_contestants"]
    assert all(len(n["reason"].split()) >= 4 for n in data["not_run"])
    md = report.to_markdown(data)
    assert "codex-cli" in md and "cursor-agent" in md


def test_s4_16_contestant_text_is_escaped_in_markdown_and_raw_in_json(tmp_path):
    text = CASES["S4-16"]["contestant_text"]
    rows = sample_rows()
    rows.append(row("KB-03", "a" * 64, "m1", "fail", 4, failed=[text]))
    data = report.results(rows, plan(), ledger_bytes=b"", cassettes=tmp_path)
    assert any(f["mode"] == text for f in data["memo"]["failure_modes"])  # raw in the JSON
    md = report.to_markdown(data)
    assert not any(ord(ch) < 32 and ch not in "\n" for ch in md)
    assert "https://evil.example" not in md
    assert not re.search(r"(?<!\\)\[[^\]]*(?<!\\)\]\(", md), "an unescaped Markdown link"
    mode_lines = [ln for ln in md.splitlines() if "ok" in ln and "x" in ln and "new row" in ln]
    assert len(mode_lines) == 1 and mode_lines[0].startswith("|")


def test_s4_19_the_report_opens_with_the_decision_memo(tmp_path):
    md = report.to_markdown(report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path))
    headings = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert headings[0] == "## Decision memo"
    assert md.index("Ranking:") < md.index("## Decision memo")
    assert "none: n \\<= 8 tasks" in md  # `<` escaped for Markdown


def test_contestants_are_ordered_by_name(tmp_path):
    md = report.to_markdown(report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path))
    section = md.split("## By contestant")[1].split("## ")[0]
    assert section.index("m1") < section.index("m2")


def test_the_report_says_which_reduction_steps_were_applied_and_the_attempts_each_contestant_got(tmp_path):
    data = report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path)
    assert data["reduction"]["applied_step"] == 1
    assert [s["why"] for s in data["reduction"]["applied"]] == ["fewer attempts for m2"]
    assert data["reduction"]["k"] == {"B": {"m1": 3, "m2": 1}}
    md = report.to_markdown(data)
    assert "fewer attempts for m2" in md and "a later step, not applied" not in md


# ── review lens 2B: a reader who has not read the design can use the report ─────────────────────────


def test_the_memo_opens_with_a_computed_answer(tmp_path):
    data = report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path)
    md = report.to_markdown(data)
    subheadings = [ln for ln in md.splitlines() if ln.startswith("### ")]
    assert subheadings[0] == "### Answer"
    answer = md[md.index("### Answer") : md.index(subheadings[1])]
    # m1 and m2 are the only pair: it is named, with its tasks-needed figure from the scorer.
    pair = data["memo"]["decision_grade"]["pairs"][0]
    assert "m1" in answer and "m2" in answer and str(pair["tasks"]) in answer
    assert "2 tasks" in answer and "no ranking" in answer.lower()


def test_the_report_says_what_each_task_and_configuration_is(tmp_path):
    md = report.to_markdown(report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path))
    assert "Write the KX-100 driver" in md and "Uncertainty budget" in md  # the task titles
    assert "| task | track |" in md
    for gloss in ("B:", "pass^k", "task-clustered"):
        assert gloss in md, gloss
    # Only the configurations the plan ran are glossed; one that did not run is under "Not run" (live run,
    # 2026-10-11: the memo described configuration A after it was voided).
    assert "- A0:" not in md and "- A:" not in md


def test_the_answer_opens_with_who_passed_everything_and_what_it_cost(tmp_path):
    # Live run: 9 of 11 contestants passed every attempt, and the memo's answer was nine "solved by every"
    # lines that never said so. The finding was the spread of cost among those who all passed.
    rows = []
    for task, sha in (("KB-03", "a" * 64), ("KB-04", "b" * 64)):
        rows += [row(task, sha, "cheap", "pass", i + 1, cost=0.001) for i in range(3)]
        rows += [row(task, sha, "dear", "pass", i + 1, cost=0.05) for i in range(3)]
        rows += [row(task, sha, "miss", o, i + 1) for i, o in enumerate(["pass", "fail", "pass"])]
    md = report.to_markdown(report.results(rows, plan(), ledger_bytes=b"", cassettes=tmp_path))
    answer = md[md.index("### Answer") : md.index("### At a glance")]
    assert "2 of 3" in answer and "B" in answer
    assert "cheap" in answer and "dear" in answer and "50" in answer  # 0.05 / 0.001 per pass
    assert "miss" in answer and "KB-03" in answer and "KB-04" in answer  # who missed, where
    assert answer.count("Solved by every") <= 1  # one line per configuration, not one per task


def test_a_difference_not_measured_says_so(tmp_path):
    md = report.to_markdown(report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path))
    section = md[md.index("## What the scaffold adds") : md.index("## Attempts per contestant")]
    assert "A − A0: not measured" in section and "A0 − B: not measured" in section


def test_the_report_has_a_task_by_contestant_table(tmp_path):
    md = report.to_markdown(report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path))
    glance = md[md.index("### At a glance") :]
    assert "B · m1" in glance and "2 / 3" in glance and "1 / 3" in glance


def test_each_pair_is_listed_with_what_telling_it_apart_would_need(tmp_path):
    md = report.to_markdown(report.results(sample_rows(), plan(), ledger_bytes=b"", cassettes=tmp_path))
    section = md[md.index("### What a decision would need") :]
    assert "| B | m1 | m2 |" in section and "5 points" in section and "15 points" in section


def test_voided_attempts_are_left_out_and_said(tmp_path):
    rows = sample_rows()
    void = {"kind": "void", "reason": "instrument bug", "at": "2026-10-11T09:00:00Z",
            "attempts": [{k: rows[0][k] for k in ("task_sha256", "config", "attempt", "at")} | {
                "model": rows[0]["contestant"]["model"], "effort": rows[0]["contestant"]["effort"]}]}  # fmt: skip
    data = report.results([*rows, void], plan(), ledger_bytes=b"", cassettes=tmp_path)
    assert sum(c["attempts"] for c in data["cells"]) == len(rows) - 1
    assert data["voided"] == [{"count": 1, "reason": "instrument bug"}]
    assert "instrument bug" in report.to_markdown(data)
