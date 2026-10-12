"""STORY-002 through `review scan`: AI models reviewed against their cards, keyed on the card (S2-10, S2-12).

The model is a fake that answers from the card's front matter, so these tests exercise the CLI, the key
and the ledger without recordings. The recorded run of the real model is checked in test_recorded.py.
"""

import io
import json
import re
import shutil
from pathlib import Path

from review.cli import main

ROOT = Path(__file__).resolve().parents[2]
SBOM = str(ROOT / "samples" / "sbom.cdx.json")
POLICY = str(ROOT / "samples" / "policy.yaml")
CARDS = ROOT / "samples" / "model-cards"


class CardReader:
    """A stand-in model: calls the tool once, then quotes the card's `license:` line."""

    def __init__(self, model_id, calls):
        self.model_id, self.calls, self.step = model_id, calls, 0

    def create(self, **request):
        self.calls.append(self.model_id)
        self.step += 1
        usage = {"input_tokens": 500, "output_tokens": 40, "inference_geo": "global"}
        if self.step == 1:
            call = {"type": "tool_use", "id": "t1", "name": "read_model_card", "input": {"model_id": self.model_id}}
            return {"stop_reason": "tool_use", "content": [call], "usage": usage}
        card = request["messages"][-1]["content"][0]["content"]
        m = re.search(r"^license: (.+)$", card, re.M)
        lic = m.group(1).strip() if m else None
        answer = {"license_id": lic, "quote": f"license: {lic}" if lic else None, "restrictions": []}
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(answer)}], "usage": usage}


def run(*argv, calls=None, factory=True):
    out, err = io.StringIO(), io.StringIO()
    kwargs = {}
    if factory:
        kwargs["provider_factory"] = lambda model_id, live, recordings: CardReader(model_id, calls)
    code = main(list(argv), out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def ai_decisions(ledger: Path):
    rows = [json.loads(line) for line in ledger.read_text("utf-8").splitlines() if line.strip()]
    return [r for r in rows if r["kind"] == "decision" and r["identity"].startswith("pkg:huggingface/")]


def test_s2_12_without_model_cards_the_scan_is_unchanged(tmp_path):
    ledger = tmp_path / "l.jsonl"
    code, _, _ = run("scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), factory=False)
    assert code == 0
    assert all("model card" not in r["reason"] and "model_card" not in r for r in ai_decisions(ledger))


def test_s2_12_offline_without_a_recording_refuses_and_calls_nothing(tmp_path):
    ledger, empty = tmp_path / "l.jsonl", tmp_path / "no-recordings"
    empty.mkdir()
    args = ["scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger)]
    code, _, err = run(*args, "--model-cards", str(CARDS), "--recordings", str(empty), factory=False)
    assert code == 2
    assert "recording" in err


def test_s2_10_a_changed_card_is_a_new_decision_and_the_same_card_is_reused(tmp_path):
    cards, ledger, calls = tmp_path / "cards", tmp_path / "l.jsonl", []
    shutil.copytree(CARDS, cards)
    args = ["scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), "--model-cards", str(cards)]

    assert run(*args, calls=calls)[0] == 0
    first = ai_decisions(ledger)
    calls_after_first = len(calls)
    assert len(first) == 3
    assert all("model card" in r["reason"] and r["model_card"]["model_id"] for r in first)

    assert run(*args, calls=calls)[0] == 0
    assert len(ai_decisions(ledger)) == 3
    assert len(calls) == calls_after_first  # reused without calling the model again

    card = cards / "mistralai__Mistral-7B-v0.1.md"
    card.write_text(card.read_text("utf-8") + "\nA new paragraph.\n", "utf-8")
    assert run(*args, calls=calls)[0] == 0
    assert len(ai_decisions(ledger)) == 4


def test_the_agent_lines_share_the_ledger_with_the_decisions(tmp_path):
    ledger = tmp_path / "l.jsonl"
    run("scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), "--model-cards", str(CARDS), calls=[])
    kinds = {json.loads(line)["kind"] for line in ledger.read_text("utf-8").splitlines() if line.strip()}
    assert {"run_start", "model_call", "tool_intent", "tool", "run_end", "decision"} <= kinds


def test_the_report_finds_decisions_made_against_the_cards(tmp_path):
    ledger, out = tmp_path / "l.jsonl", tmp_path / "out"
    base = ["--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), "--model-cards", str(CARDS)]
    assert run("scan", *base, calls=[])[0] == 0
    code, _, err = run("report", *base, "--out", str(out), factory=False)
    assert code == 0, err
    report = json.loads((out / "report.json").read_text("utf-8"))
    llama = next(r for r in report["components"] if r["name"] == "Llama-3.1-8B")
    assert "model card" in llama["reason"]


class DownProvider:
    """A provider that cannot be reached: every call raises `error`."""

    def __init__(self, error):
        self.error = error

    def create(self, **request):
        raise self.error


def _api_connection_error():
    import anthropic

    # The SDK keeps the request it was given and does not use it to build the error, so a stand-in is enough
    # and the test does not depend on which HTTP library the SDK uses underneath.
    return anthropic.APIConnectionError(request=object())  # type: ignore[arg-type]


def run_down(error, ledger: Path):
    out, err = io.StringIO(), io.StringIO()
    argv = ["scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), "--model-cards", str(CARDS)]
    code = main(argv, out=out, err=err, provider_factory=lambda model_id, live, recordings: DownProvider(error))
    return code, err.getvalue()


def test_s2_13_a_model_that_cannot_be_reached_refuses_cleanly_and_records_no_decision_for_it(tmp_path):
    for error in (ConnectionError("API down"), TimeoutError("slow"), _api_connection_error()):
        ledger = tmp_path / f"{type(error).__name__}.jsonl"
        code, err = run_down(error, ledger)
        assert code == 2, err
        assert err.startswith("refused:") and type(error).__name__ in err
        assert ai_decisions(ledger) == []  # no decision for the model: a re-run decides it when it answers
        rows = [json.loads(line) for line in ledger.read_text("utf-8").splitlines() if line.strip()]
        assert any(r["kind"] == "run_end" and r.get("error") for r in rows)  # the failed run is in the history
        ai_allows = [r for r in rows if r["kind"] == "decision" and r["identity"].startswith("pkg:huggingface/")]
        assert not any(r["verdict"] == "Allow" for r in ai_allows)


def test_s2_13_the_rerun_decides_what_was_left_and_reuses_the_rest(tmp_path):
    ledger, calls = tmp_path / "l.jsonl", []
    code, _ = run_down(ConnectionError("API down"), ledger)
    assert code == 2
    decided_before = len([line for line in ledger.read_text("utf-8").splitlines() if '"kind": "decision"' in line])
    args = ["scan", "--sbom", SBOM, "--policy", POLICY, "--ledger", str(ledger), "--model-cards", str(CARDS)]
    code, out, _ = run(*args, calls=calls)[0:3]
    assert code == 0
    assert len(ai_decisions(ledger)) == 3
    assert f"{decided_before} reused" in out


def test_s2_13_an_error_that_is_not_an_outage_is_not_swallowed(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        run_down(ValueError("a bug"), tmp_path / "l.jsonl")
