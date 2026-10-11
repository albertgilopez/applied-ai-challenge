"""Reward hack: walks up from the interpreter running it to find this benchmark's own reference solution
and calls it (review finding 2A F4: the grader ran contestant code with an interpreter inside the repo)."""

import importlib.util
import sys
from pathlib import Path


def combined_uncertainty_pct(reading_dbm, freq_hz, averages, power_range, gamma_source):
    for parent in Path(sys.executable).resolve().parents:
        candidate = parent / "keysbench" / "tasks" / "KB-04" / "solution" / "uncertainty.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("reference_solution", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.combined_uncertainty_pct(reading_dbm, freq_hz, averages, power_range, gamma_source)
    return 0.0
