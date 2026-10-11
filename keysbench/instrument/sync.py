"""Copy the KX-100 simulator and manual into the domain tasks that use them.

A task's `environment/` must be self-contained (it is what a contestant gets, and what the grader starts
from), so each domain task carries its own copy. `python -m keysbench.instrument.sync` writes the copies;
`tests/story_004/test_instrument_copies.py` fails if any copy differs from the source, so a change to the
simulator or the manual cannot leave a task on an old version (and the task digest changes with it).
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE.parent / "tasks"
SOURCES = {"kx100.py": HERE / "sim.py", "MANUAL.md": HERE / "MANUAL.md"}
# task -> paths inside the task. KB-03's hidden tests get their own copy of the simulator: the oracle runs
# in the test process on the host, never next to the contestant's code.
COPIES = {
    "KB-03": ("environment/kx100.py", "environment/MANUAL.md", "tests/kx100.py"),
    "KB-04": ("environment/MANUAL.md",),
    "KB-05": ("environment/MANUAL.md",),
    "KB-06": ("environment/MANUAL.md",),
}


def expected_copies() -> dict[Path, bytes]:
    return {TASKS / task / rel: SOURCES[Path(rel).name].read_bytes() for task, rels in COPIES.items() for rel in rels}


def sync() -> list[Path]:
    written = []
    for path, data in expected_copies().items():
        if path.parent.parent.is_dir() and (not path.exists() or path.read_bytes() != data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            written.append(path)
    return written


if __name__ == "__main__":
    for p in sync():
        print("wrote", p.relative_to(TASKS.parent.parent).as_posix())
