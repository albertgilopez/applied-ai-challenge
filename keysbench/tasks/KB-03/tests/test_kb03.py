"""Hidden tests for KB-03: the driver, run in a container, against a simulator that stays in this process.

The driver gets a session with only write/read/query, carried over a pipe (kbcall.drive). Everything
checked comes from this side: the simulator's state after the run (its frequency and averaging settings,
how many reads it served without a fresh INIT) and its noiseless oracle. The driver can reach neither,
and nothing it prints counts except its one result message.
"""

import math

import kx100
from kbcall import drive

CASES = [  # seed, signal frequency, signal power, averaging count
    (11, 2.4e9, -23.0, 16),
    (12, 12.0e9, -8.0, 64),
    (13, 300e6, -41.5, 16),
]


def run(seed: int, hz: float, dbm: float, freq: float, n: int) -> tuple[dict, kx100.KX100]:
    sim = kx100.KX100(seed, signal_hz=hz, signal_dbm=dbm)
    return drive(sim, freq, n, timeout_s=60), sim


def tolerance_db(n: int) -> float:
    # The simulator's noise is 2 % / sqrt(N), clamped at 3 sigma; plus the 0.01 dB display step.
    return 10 * math.log10(1 + 3 * 0.02 / math.sqrt(n)) + 0.011


def test_reads_the_signal_power():
    for seed, hz, dbm, n in CASES:
        result, _ = run(seed, hz, dbm, hz, n)
        assert result.get("kind") == "value" and type(result.get("value")) is float, result
        expected = kx100.KX100(seed, signal_hz=hz, signal_dbm=dbm).expected_dbm(freq_hz=hz)
        assert abs(result["value"] - expected) <= tolerance_db(n), (seed, result["value"], expected)


def test_sets_the_frequency_and_the_averaging_count():
    seed, hz, dbm, n = CASES[0]
    _, sim = run(seed, hz, dbm, hz, n)
    sim.write("*CLS")
    assert float(sim.query("SENS:FREQ?")) == hz
    assert int(sim.query("SENS:AVER:COUN?")) == n


def test_takes_a_fresh_measurement():
    for seed, hz, dbm, n in CASES:
        result, sim = run(seed, hz, dbm, hz, n)
        assert result.get("kind") == "value", result
        assert sim.stale_fetches == 0


def test_raises_on_an_instrument_error():
    # 40 GHz is outside the band: the meter refuses the setting and queues an error.
    result, _ = run(14, 2.4e9, -20.0, 40e9, 16)
    assert result.get("kind") == "InstrumentError", result
