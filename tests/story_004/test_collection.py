"""Task trees are data: the repo's own test run never collects anything under keysbench/tasks/.

They hold hidden tests, old copies of core/ and planted reward hacks (a conftest.py that rewrites every
result, a pytest.py that fakes a report). Collected by the repo's suite, they would run as if they were
the repo's tests; this checks the actual collection, not the configuration that is meant to prevent it.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_suite_collects_nothing_under_the_task_trees():
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    ).stdout
    collected = [line for line in out.splitlines() if "::" in line]
    assert collected, out[-500:]  # the collection ran
    assert not [line for line in collected if "keysbench/tasks" in line.replace("\\", "/")]
