"""Every domain task carries the current KX-100 simulator and manual, byte for byte."""

from keysbench.instrument.sync import expected_copies


def test_task_copies_of_the_instrument_match_the_source():
    stale = [p for p, data in expected_copies().items() if p.parent.parent.is_dir() and p.read_bytes() != data]
    missing = [p for p in expected_copies() if p.parent.parent.is_dir() and not p.exists()]
    assert not stale and not missing, f"run python -m keysbench.instrument.sync: stale {stale}, missing {missing}"
