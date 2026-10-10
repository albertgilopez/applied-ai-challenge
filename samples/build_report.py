"""Build the sample report Legal would attach: scan (AI models against their cards), one reviewer
override, the report. Offline: the model's answers are the recordings in tests/cassettes/story_002.

    uv run python samples/build_report.py

Writes samples/report/{ledger.jsonl, report.json, report.md}. The ledger is rebuilt from scratch each
time, so the files show exactly what these steps produce.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from review.cli import main  # noqa: E402

OUT = ROOT / "samples" / "report"
SBOM = str(ROOT / "samples" / "sbom.cdx.json")
POLICY = str(ROOT / "samples" / "policy.yaml")
CARDS = str(ROOT / "samples" / "model-cards")
LEDGER = OUT / "ledger.jsonl"
NOW = "2026-10-10T08:00:00Z"


def run(*argv: str) -> str:
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), now=lambda: NOW, out=out, err=err)
    if code != 0:
        raise SystemExit(f"{argv[0]} refused: {err.getvalue()}")
    return out.getvalue()


def decision_id(name: str) -> str:
    rows = [json.loads(line) for line in LEDGER.read_text("utf-8").splitlines() if line.strip()]
    return str(next(r["id"] for r in rows if r["kind"] == "decision" and r["name"] == name))


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGER.unlink(missing_ok=True)
    print(run("scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(LEDGER), "--model-cards", CARDS), end="")
    print(
        run(
            "override",
            "--ledger",
            str(LEDGER),
            "--decision",
            decision_id("Llama-3.1-8B"),
            "--verdict",
            "Allow",
            "--by",
            "A. Reviewer",
            "--reason",
            "Under 700M monthly active users; 'Built with Llama' shown on the about page; AUP accepted",
        ),
        end="",
    )
    print(
        run(
            "report",
            "--sbom",
            SBOM,
            "--policy",
            POLICY,
            "--ledger",
            str(LEDGER),
            "--out",
            str(OUT),
            "--model-cards",
            CARDS,
        ),
        end="",
    )


if __name__ == "__main__":
    build()
