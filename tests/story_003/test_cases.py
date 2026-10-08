"""STORY-003 cases end to end: every case through the CLI (`review.cli.main`), on a temp ledger.

The CLI is driven in-process so each case runs the real file adapter, the real ledger and the real
report writer; one smoke test at the end runs `python -m review` as a separate process.
"""

import io
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
import yaml

from review.cli import main
from tests.story_001.cases import load_cases

CASES = load_cases("STORY-003")
REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / "samples"
POLICY = SAMPLES / "policy.yaml"


class Run:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.ledger = tmp / "ledger.jsonl"
        self.out = tmp / "out"
        self.clock = iter(f"2026-10-09T00:00:{i:02d}Z" for i in range(60))

    def __call__(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = main([*args], now=lambda: next(self.clock), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def sbom(self, *components: dict, name: str = "sbom.cdx.json") -> Path:
        doc = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [self._cdx(c) for c in components]}
        path = self.tmp / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    @staticmethod
    def _cdx(c: dict) -> dict:
        out = {"type": "library", "name": c["name"], "version": c.get("version")}
        if c.get("license"):
            out["licenses"] = [{"expression": c["license"]}]
        if c.get("source"):
            out["externalReferences"] = [{"type": "vcs", "url": c["source"]}]
        return out

    def policy(self, data: dict) -> Path:
        path = self.tmp / "policy-2.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    def lines(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return [json.loads(x) for x in self.ledger.read_text(encoding="utf-8").splitlines() if x.strip()]

    def kinds(self) -> list[str]:
        return [r["kind"] for r in self.lines()]

    def decisions(self) -> list[dict]:
        return [r for r in self.lines() if r["kind"] == "decision"]

    def scan(self, sbom: Path, policy: Path = POLICY) -> None:
        code, _, err = self("scan", "--sbom", str(sbom), "--policy", str(policy), "--ledger", str(self.ledger))
        assert code == 0, err

    def override(self, decision: str, o: dict) -> tuple[int, str, str]:
        args = ["override", "--ledger", str(self.ledger), "--decision", decision, "--verdict", o["verdict"]]
        args += ["--by", o.get("by", "")]
        if "reason" in o:
            args += ["--reason", o["reason"]]
        return self(*args)

    def approve(self, decision: str, by: str) -> tuple[int, str, str]:
        return self("approve", "--ledger", str(self.ledger), "--decision", decision, "--by", by)

    def report(self, sbom: Path, policy: Path = POLICY) -> dict:
        code, _, err = self(
            "report", "--sbom", str(sbom), "--policy", str(policy), "--ledger", str(self.ledger), "--out", str(self.out)
        )
        assert code == 0, err
        return json.loads((self.out / "report.json").read_text(encoding="utf-8"))


@pytest.fixture
def run(tmp_path):
    return Run(tmp_path)


def test_override_is_a_new_line_and_the_decision_stays(run):  # S3-01
    case = CASES["S3-01"]
    sbom = run.sbom(case["component"])
    run.scan(sbom)
    first = run.ledger.read_bytes()
    [decision] = run.decisions()
    code, _, err = run.override(decision["id"], case["steps"][0]["override"])
    assert code == 0, err
    assert run.kinds() == ["decision", "override"]
    assert run.ledger.read_bytes().startswith(first)  # the decision line is byte-for-byte unchanged
    assert run.lines()[1]["decision"] == decision["id"]


@pytest.mark.parametrize("row", CASES["S3-02"]["rows"], ids=["empty-by", "blank-by", "empty-reason", "no-reason"])
def test_override_without_reviewer_or_reason_is_refused(run, row):  # S3-02
    run.scan(run.sbom(CASES["S3-02"]["component"]))
    [decision] = run.decisions()
    code, _, err = run.override(decision["id"], row["override"])
    assert code == 2 and err
    assert run.kinds() == CASES["S3-02"]["expected_after_all"]["ledger_kinds"]


def test_report_shows_the_final_verdict_and_every_override(run):  # S3-03
    case = CASES["S3-03"]
    sbom = run.sbom(case["component"])
    run.scan(sbom)
    [decision] = run.decisions()
    for step in case["steps"]:
        assert run.override(decision["id"], step["override"])[0] == 0
    [row] = run.report(sbom)["components"]
    expected = case["expected"]
    assert (row["verdict"], row["decided_verdict"], row["status"]) == (
        expected["final_verdict"],
        expected["decided_verdict"],
        expected["status"],
    )
    assert [(r["by"], r["verdict"]) for r in row["reviews"]] == [
        (e["by"], e["verdict"]) for e in expected["reviews_listed"]
    ]
    md = (run.out / "report.md").read_text(encoding="utf-8")
    assert all(e["by"] in md for e in expected["reviews_listed"])


def test_counts_and_a_source_per_component(run):  # S3-04
    sbom = REPO / CASES["S3-04"]["sbom"]
    run.scan(sbom)
    report = run.report(sbom)
    counts = report["counts"]
    assert counts["Allow"] + counts["Needs review"] + counts["Reject"] == len(report["components"]) >= 10
    for row in report["components"]:
        assert row["source_url"] is None or row["source_url"].startswith("https://")
    md = (run.out / "report.md").read_text(encoding="utf-8")
    assert md.count("| <https://") + md.count("| none declared |") == len(report["components"])


def test_a_second_run_reuses_the_recorded_verdicts(run):  # S3-05
    sbom = REPO / CASES["S3-05"]["sbom"]
    run.scan(sbom)
    first = run.report(sbom)
    decisions = run.decisions()
    run.scan(sbom)
    second = run.report(sbom)
    assert run.decisions() == decisions  # no new decision line
    assert first["generated_at"] != second["generated_at"]
    assert {**first, "generated_at": None} == {**second, "generated_at": None}


@pytest.mark.parametrize("row", CASES["S3-06"]["rows"], ids=["unknown-decision", "unknown-verdict", "approve-unknown"])
def test_unknown_decision_or_verdict_is_refused(run, row):  # S3-06
    run.scan(run.sbom(CASES["S3-06"]["component"]))
    [decision] = run.decisions()
    if "override" in row:
        o = row["override"]
        code, _, err = run.override(o.get("decision", decision["id"]), o)
    else:
        code, _, err = run.approve(row["approve"]["decision"], row["approve"]["by"])
    assert code == 2 and err
    assert run.kinds() == ["decision"]


def test_approve_needs_a_reviewer_and_clears_pending(run):  # S3-07
    case = CASES["S3-07"]
    sbom = run.sbom(case["component"])
    run.scan(sbom)
    [decision] = run.decisions()
    refused, approved = case["rows"]
    assert run.approve(decision["id"], refused["approve"]["by"])[0] == 2
    assert run.approve(decision["id"], approved["approve"]["by"])[0] == 0
    report = run.report(sbom)
    [row] = report["components"]
    expected = approved["expected"]
    assert (row["status"], row["verdict"], report["counts"]["pending"]) == (
        expected["status"],
        expected["final_verdict"],
        expected["pending"],
    )
    code, listed, _ = run("list", "--ledger", str(run.ledger))
    assert code == 0 and decision["id"] not in listed


def test_same_identity_different_license_gets_separate_decisions(run):  # S3-08
    case = CASES["S3-08"]
    sbom = run.sbom(*case["components"])
    run.scan(sbom)
    decisions = run.decisions()
    assert len(decisions) == case["expected"]["decisions"]
    step = case["steps"][0]["override"]
    assert run.override(decisions[step["component"]]["id"], step)[0] == 0
    rows = {r["decided_verdict"]: r for r in run.report(sbom)["components"]}
    assert sorted(rows) == sorted(case["expected"]["verdicts"])
    assert rows["Reject"]["status"] == case["expected"]["second_component_status"]


def test_a_policy_change_decides_again_and_drops_the_old_override(run):  # S3-09
    case = CASES["S3-09"]
    sbom = run.sbom(case["component"])
    run.scan(sbom)
    [decision] = run.decisions()
    assert run.override(decision["id"], case["steps"][0]["override"])[0] == 0
    new_policy = run.policy(case["steps"][1]["rescan_with_policy"])
    run.scan(sbom, new_policy)
    assert len(run.decisions()) == case["expected"]["decisions"]
    [row] = run.report(sbom, new_policy)["components"]
    assert (row["verdict"], row["status"]) == (case["expected"]["final_verdict"], case["expected"]["status"])


@pytest.mark.parametrize("row", CASES["S3-10"]["rows"], ids=lambda r: r["source"][:20])
def test_only_https_reaches_the_report(run, row):  # S3-10
    sbom = run.sbom({"name": "x", "version": "1.0", "license": "MIT", "source": row["source"]})
    run.scan(sbom)
    [component] = run.report(sbom)["components"]
    expected = None if row["expected"] == "none declared" else row["expected"]
    assert component["source_url"] == expected


def test_hostile_text_cannot_break_the_report_or_the_terminal(run):  # S3-11
    case = CASES["S3-11"]
    sbom = run.sbom(case["component"])
    run.scan(sbom)
    report = run.report(sbom)
    md = (run.out / "report.md").read_text(encoding="utf-8")
    assert report["components"][0]["name"] == case["component"]["name"]
    assert not any(unicodedata.category(ch) in ("Cc", "Cf") for ch in md.replace("\n", ""))
    assert "https://evil" not in md
    _, listed, _ = run("list", "--ledger", str(run.ledger))
    assert "\x1b" not in listed and listed.count("\n") == 1  # one pending item, one line


def test_the_report_names_the_product_or_says_every_package_was_reviewed(run):  # S3-12
    cdx, spdx = CASES["S3-12"]["rows"]
    sample = REPO / cdx["sbom"]
    run.scan(sample)
    run.report(sample)
    assert "sample-instrument-software@3.2.0" in (run.out / "report.md").read_text(encoding="utf-8")

    two = run.tmp / "two.spdx.json"
    pkg = lambda n: {"SPDXID": f"SPDXRef-{n}", "name": n, "versionInfo": "1.0", "licenseConcluded": "MIT"}  # noqa: E731
    two.write_text(
        json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "SPDXID": "SPDXRef-DOCUMENT",
                "documentDescribes": ["SPDXRef-a", "SPDXRef-b"],
                "packages": [pkg("a"), pkg("b")],
            }
        ),
        encoding="utf-8",
    )
    run.scan(two)
    report = run.report(two)
    assert report["product"] is None and len(report["components"]) == 2
    assert "every package" in (run.out / "report.md").read_text(encoding="utf-8")


def test_report_before_scan_is_refused(run):  # DR-9
    sbom = run.sbom({"name": "x", "version": "1.0", "license": "MIT"})
    code, _, err = run(
        "report", "--sbom", str(sbom), "--policy", str(POLICY), "--ledger", str(run.ledger), "--out", str(run.out)
    )
    assert code == 2 and "scan first" in err
    assert not (run.out / "report.json").exists()


def test_python_dash_m_review_runs(tmp_path):  # entry point smoke test
    ledger = tmp_path / "ledger.jsonl"
    sbom = SAMPLES / "sbom.cdx.json"
    r = subprocess.run(
        [sys.executable, "-m", "review", "scan", "--sbom", str(sbom), "--policy", str(POLICY), "--ledger", str(ledger)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert ledger.exists()
