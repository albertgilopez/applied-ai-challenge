"""STORY-002 S2-12 on the real model's answers: the recorded run replays offline, through `review scan`.

The recordings in tests/cassettes/story_002 were made once with `scan --live` (claude-haiku-5-5, effort
medium). Replaying them proves the whole path without a network or a key: the request the code builds
today must be byte-for-byte the one that was recorded, or the replay stops.
"""

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SBOM = str(ROOT / "samples" / "sbom.cdx.json")
POLICY = str(ROOT / "samples" / "policy.yaml")
CARDS = str(ROOT / "samples" / "model-cards")
RECORDINGS = ROOT / "tests" / "cassettes" / "story_002"


def test_s2_12_the_recorded_run_replays_offline_with_the_expected_verdicts(tmp_path, monkeypatch):
    from review.cli import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # a replay that needed the network would fail here
    ledger = tmp_path / "l.jsonl"
    err = io.StringIO()
    args = ["scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), "--model-cards", CARDS]
    assert main(args, out=io.StringIO(), err=err) == 0, err.getvalue()

    rows = [json.loads(line) for line in ledger.read_text("utf-8").splitlines() if line.strip()]
    ai = {r["name"]: r for r in rows if r["kind"] == "decision" and "model_card" in r}
    assert {name: r["verdict"] for name, r in ai.items()} == {
        "Mistral-7B-v0.1": "Allow",
        "Llama-3.1-8B": "Needs review",
        "gemma-2-2b": "Needs review",
    }
    assert all(r["model_card"]["grounded"] for r in ai.values())
    assert ai["Llama-3.1-8B"]["model_card"]["license"] == "LicenseRef-llama3.1"
    assert any("700 million" in x["quote"] for x in ai["Llama-3.1-8B"]["model_card"]["restrictions"])


def test_the_recordings_hold_no_credential():
    for path in RECORDINGS.glob("*.jsonl"):
        text = path.read_text("utf-8").lower()
        assert "sk-ant" not in text and "x-api-key" not in text and "api_key" not in text, path.name
