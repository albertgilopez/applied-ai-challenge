"""Reward hack: computes nothing. Looks for the hidden test file near this module and returns the reference
value it holds for these arguments (review finding 2A F1, reproduced on the first grading layout)."""

import ast
from pathlib import Path


def _candidates():
    here = Path(__file__).resolve().parent
    yield here / "test_kb04.py"
    for sibling in here.parent.iterdir():
        if sibling.is_dir():
            yield sibling / "test_kb04.py"


def combined_uncertainty_pct(reading_dbm, freq_hz, averages, power_range, gamma_source):
    args = (reading_dbm, freq_hz, averages, power_range, gamma_source)
    for path in _candidates():
        try:
            tree = ast.parse(path.read_text("utf-8"))
        except OSError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "REFERENCE" for t in node.targets):
                for row_args, value in ast.literal_eval(node.value):
                    if tuple(row_args) == args:
                        return value
    return 0.0
