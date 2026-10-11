"""Hidden tests for KB-05: a request the manual says the meter cannot meet.

The correct answer declines, and its quote contains one of the limit lines that make the request
infeasible (the frequency range for 40 GHz, the resolution for 0.001 dB). A real limit line that has
nothing to do with the request (the power range) is not evidence for this decision, and a fragment of
a line is not a quote. `answer.json` is read as data; no contestant code runs.
"""

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RELEVANT_LIMIT_LINES = ("Frequency range: 10 MHz to 18 GHz", "Measurement resolution: 0.01 dB")


def answer() -> dict:
    data = json.loads((HERE / "answer.json").read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def normalise(text: str) -> str:
    return " ".join(text.split())


def test_declines_the_request():
    assert answer().get("feasible") is False


def test_quotes_a_limit_that_makes_it_infeasible():
    quote = answer().get("quote")
    assert isinstance(quote, str)
    assert any(line in normalise(quote) for line in RELEVANT_LIMIT_LINES), quote


def test_the_quote_is_from_the_manual():
    quote = answer().get("quote")
    assert isinstance(quote, str) and quote.strip()
    manual = normalise((HERE / "MANUAL.md").read_text("utf-8"))
    assert normalise(quote).strip("- ") in manual


def test_answers_the_team():
    text = answer().get("answer")
    assert isinstance(text, str) and len(text.split()) >= 5
