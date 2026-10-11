"""Hidden tests for KB-03: the driver, run against the simulator in its own process.

The driver gets a session with only write/read/query. What is checked comes from the simulator's
state after the run (its frequency and averaging settings, how many reads it served without a fresh
INIT) and from its noiseless oracle, computed here, in the test's process.
"""

import math

import kx100
from kbcall import call

SETUP = """
import kx100, driver
sim = kx100.KX100({seed}, signal_hz={hz!r}, signal_dbm={dbm!r})
class Session:
    def write(self, cmd):
        sim.write(cmd)
    def read(self):
        return sim.read()
    def query(self, cmd):
        return sim.query(cmd)
try:
    outcome = ["value", driver.measure_power(Session(), {freq!r}, {n!r})]
except driver.InstrumentError as e:
    outcome = ["InstrumentError", str(e)[:200]]
except Exception as e:
    outcome = ["other", type(e).__name__]
_out = {{"outcome": outcome, "stale": sim.stale_fetches,
        "freq": sim.query("SENS:FREQ?"), "aver": sim.query("SENS:AVER:COUN?")}}
"""

CASES = [  # seed, signal frequency, signal power, averaging count
    (11, 2.4e9, -23.0, 16),
    (12, 12.0e9, -8.0, 64),
    (13, 300e6, -41.5, 16),
]


def run(seed: int, hz: float, dbm: float, freq: float, n: int) -> dict:
    return call("_out", setup=SETUP.format(seed=seed, hz=hz, dbm=dbm, freq=freq, n=n), timeout_s=60)


def tolerance_db(n: int) -> float:
    # The simulator's noise is 2 % / sqrt(N), clamped at 3 sigma; plus the 0.01 dB display step.
    return 10 * math.log10(1 + 3 * 0.02 / math.sqrt(n)) + 0.011


def test_reads_the_signal_power():
    for seed, hz, dbm, n in CASES:
        got = run(seed, hz, dbm, hz, n)
        kind, value = got["outcome"]
        assert kind == "value" and type(value) is float, got["outcome"]
        expected = kx100.KX100(seed, signal_hz=hz, signal_dbm=dbm).expected_dbm(freq_hz=hz)
        assert abs(value - expected) <= tolerance_db(n), (seed, value, expected)


def test_sets_the_frequency_and_the_averaging_count():
    seed, hz, dbm, n = CASES[0]
    got = run(seed, hz, dbm, hz, n)
    assert float(got["freq"]) == hz
    assert int(got["aver"]) == n


def test_takes_a_fresh_measurement():
    for seed, hz, dbm, n in CASES:
        assert run(seed, hz, dbm, hz, n)["stale"] == 0


def test_raises_on_an_instrument_error():
    # 40 GHz is outside the band: the meter refuses the setting and queues an error.
    got = run(14, 2.4e9, -20.0, 40e9, 16)
    assert got["outcome"][0] == "InstrumentError", got["outcome"]
