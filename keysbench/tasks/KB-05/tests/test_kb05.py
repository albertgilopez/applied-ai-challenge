"""Hidden tests for KB-05: a request the manual says the meter cannot meet.

The correct answer declines, and its quote contains one of the limit lines that make the request
infeasible (the frequency range for 40 GHz, the resolution for 0.001 dB). A real limit line that has
nothing to do with the request (the power range) is not evidence for this decision, and a fragment of
a line is not a quote. `answer.json` is read as data; no contestant code runs.
"""

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
CODE = HERE.parent / "code"  # the contestant's files, read as data
# The instruction asks for "the sentence or line of MANUAL.md your decision rests on". In the manual's
# section 6 those are the two limits the request breaks and the sentence that says what follows from them
# (either of its clauses). Corrected after the live grid: Sonnet, Opus and Fable quoted that sentence, and
# a key with the two limit lines only failed them for doing what the instruction asked.
RELEVANT_LIMIT_LINES = (
    "Frequency range: 10 MHz to 18 GHz",
    "Measurement resolution: 0.01 dB",
    "a reading finer than the resolution is not available from the instrument",
    "a signal outside the frequency range cannot be measured with a calibrated result",
)
IRRELEVANT_LIMIT_LINES = ("Power range: -60 dBm to +20 dBm",)


def answer() -> dict:
    data = json.loads((CODE / "answer.json").read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def normalise(text: str) -> str:
    return " ".join(text.split())


def test_declines_the_request():
    assert answer().get("feasible") is False


def test_quotes_a_limit_that_makes_it_infeasible():
    quote = answer().get("quote")
    assert isinstance(quote, str)
    # Case-blind here: "copied exactly" is the next test's job.
    assert any(line.lower() in normalise(quote).lower() for line in RELEVANT_LIMIT_LINES), quote


def test_quotes_only_the_limits_that_apply():
    # Quoting the whole limits block contains the right line by construction; it is not the evidence.
    quote = answer().get("quote")
    assert isinstance(quote, str)
    assert not any(line in normalise(quote) for line in IRRELEVANT_LIMIT_LINES), quote


def test_the_quote_is_from_the_manual():
    quote = answer().get("quote")
    assert isinstance(quote, str) and quote.strip()
    manual = normalise((CODE / "MANUAL.md").read_text("utf-8"))
    assert normalise(quote).strip("- ") in manual


def test_answers_the_team():
    text = answer().get("answer")
    assert isinstance(text, str) and len(text.split()) >= 5
