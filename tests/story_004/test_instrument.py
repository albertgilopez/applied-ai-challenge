"""T3: the KX-100 simulator and its manual (feeds KB-03..KB-06).

The simulator is the oracle the domain tasks are graded against, so its behaviour is pinned here:
the documented commands, the error queue, the stale read that KB-03's antipattern falls into, and
that every number KB-04 and every limit line KB-05 cite are written in the manual exactly as the
code declares them.
"""

from __future__ import annotations

import math
import statistics

import pytest

from keysbench.instrument.sim import (
    COMMANDS,
    KX100,
    LIMIT_LINES,
    MANUAL_PATH,
    RESET_READING_DBM,
    SPEC_TABLE_ROWS,
    KX100Timeout,
)


def _measure(sim: KX100, freq_hz: float | None, count: int) -> float:
    if freq_hz is not None:
        sim.write(f"SENS:FREQ {freq_hz}")
    sim.write(f"SENS:AVER:COUN {count}")
    sim.write("INIT")
    assert sim.query("*OPC?") == "1"
    return float(sim.query("FETC?"))


def _errors(sim: KX100) -> list[str]:
    out = []
    while True:
        e = sim.query("SYST:ERR?")
        if e.startswith("0,"):
            return out
        out.append(e)


# --- identity and reset --------------------------------------------------------------------------


def test_idn_names_the_maker_model_serial_and_firmware():
    idn = KX100(seed=7).query("*IDN?")
    maker, model, serial, firmware = idn.split(",")
    assert model == "KX-100"
    assert serial == "KX000007"
    assert maker and firmware


def test_rst_restores_the_documented_defaults_and_the_reset_reading():
    sim = KX100(seed=1)
    sim.write("SENS:FREQ 12e9")
    sim.write("SENS:AVER:COUN 64")
    sim.write("CONF:POW:RANG HIGH")
    sim.write("INIT")
    sim.write("*RST")
    assert float(sim.query("SENS:FREQ?")) == 50e6
    assert int(sim.query("SENS:AVER:COUN?")) == 1
    assert sim.query("CONF:POW:RANG?") == "AUTO"
    assert float(sim.query("FETC?")) == RESET_READING_DBM


def test_opc_query_answers_one():
    assert KX100(seed=0).query("*OPC?") == "1"


def test_long_forms_lowercase_unit_suffix_and_termination_are_accepted():
    sim = KX100(seed=0)
    sim.write("sense:frequency 2.4 GHZ\n")
    sim.write("SENSe:AVERage:COUNt 8")
    assert float(sim.query("SENS:FREQ?")) == 2.4e9
    assert int(sim.query("sens:aver:coun?")) == 8
    assert _errors(sim) == []


# --- error queue ---------------------------------------------------------------------------------


def test_errors_are_queued_first_in_first_out_and_then_no_error():
    sim = KX100(seed=0)
    sim.write("FOO:BAR 1")
    sim.write("SENS:AVER:COUN 0")
    sim.write("CONF:POW:RANG MEDIUM")
    sim.write("SENS:FREQ")
    sim.write("SENS:AVER:COUN many")
    sim.write("INIT 3")
    assert sim.query("SYST:ERR?") == '-113,"Undefined header"'
    assert sim.query("SYST:ERR?") == '-222,"Data out of range"'
    assert sim.query("SYST:ERR?") == '-224,"Illegal parameter value"'
    assert sim.query("SYST:ERR?") == '-109,"Missing parameter"'
    assert sim.query("SYST:ERR?") == '-104,"Data type error"'
    assert sim.query("SYST:ERR?") == '-108,"Parameter not allowed"'
    assert sim.query("SYST:ERR?") == '0,"No error"'


def test_a_full_error_queue_keeps_the_oldest_and_ends_in_overflow():
    sim = KX100(seed=0)
    for _ in range(15):
        sim.write("NOPE")
    errs = _errors(sim)
    assert len(errs) == 10
    assert errs[:9] == ['-113,"Undefined header"'] * 9
    assert errs[9] == '-350,"Queue overflow"'


def test_cls_clears_the_error_queue():
    sim = KX100(seed=0)
    sim.write("NOPE")
    sim.write("*CLS")
    assert sim.query("SYST:ERR?") == '0,"No error"'


@pytest.mark.parametrize("bad", ["40e9", "5e6", "18.000001e9", "-1"])
def test_a_frequency_outside_the_band_is_refused_and_the_setting_kept(bad):
    sim = KX100(seed=0)
    sim.write("SENS:FREQ 2e9")
    sim.write(f"SENS:FREQ {bad}")
    assert sim.query("SYST:ERR?") == '-222,"Data out of range"'
    assert float(sim.query("SENS:FREQ?")) == 2e9


@pytest.mark.parametrize("edge", ["10e6", "18e9"])
def test_the_band_edges_are_accepted(edge):
    sim = KX100(seed=0)
    sim.write(f"SENS:FREQ {edge}")
    assert _errors(sim) == []
    assert float(sim.query("SENS:FREQ?")) == float(edge)


# --- session: read, timeout, interrupted query ---------------------------------------------------


def test_read_with_nothing_pending_times_out_and_queues_unterminated():
    sim = KX100(seed=0)
    with pytest.raises(KX100Timeout):
        sim.read()
    assert sim.query("SYST:ERR?") == '-420,"Query UNTERMINATED"'


def test_a_new_command_before_reading_discards_the_answer_and_queues_interrupted():
    sim = KX100(seed=0)
    sim.write("*IDN?")
    sim.write("SENS:FREQ 1e9")
    assert sim.query("SYST:ERR?") == '-410,"Query INTERRUPTED"'
    with pytest.raises(KX100Timeout):
        sim.read()


# --- the stale read (KB-03 antipattern) ----------------------------------------------------------


def test_fetch_before_any_init_returns_the_reset_reading():
    sim = KX100(seed=3)
    sim.write("SENS:FREQ 12e9")
    assert float(sim.query("FETC?")) == RESET_READING_DBM
    assert sim.stale_fetches == 1


def test_fetch_without_init_returns_the_previous_measurement_not_a_new_one():
    sim = KX100(seed=3, signal_hz=12e9)
    first = _measure(sim, 12e9, 256)
    sim.write("SENS:FREQ 1e9")
    assert float(sim.query("FETC?")) == first
    assert sim.stale_fetches == 1
    sim.write("INIT")
    assert float(sim.query("FETC?")) != first
    assert sim.stale_fetches == 1


# --- physics: frequency, averaging, range --------------------------------------------------------


def test_the_reading_depends_on_the_frequency_set():
    right = _measure(KX100(seed=5, signal_hz=12e9), 12e9, 256)
    unset = _measure(KX100(seed=5, signal_hz=12e9), None, 256)
    truth = KX100(seed=5, signal_hz=12e9).true_power_dbm
    assert abs(right - truth) <= 0.03
    assert abs(unset - truth) > 0.2


def test_averaging_reduces_the_noise():
    err1, err256 = [], []
    for seed in range(60):
        ideal = KX100(seed=seed).expected_dbm()
        err1.append(_measure(KX100(seed=seed), KX100(seed=seed).signal_hz, 1) - ideal)
        err256.append(_measure(KX100(seed=seed), KX100(seed=seed).signal_hz, 256) - ideal)
    # same seed, same measurement index -> same z: the larger count can only shrink the error
    for a, b in zip(err1, err256, strict=True):
        assert abs(b) <= abs(a) + 0.01
    assert statistics.pstdev(err1) > 0.05
    assert statistics.pstdev(err256) < 0.012
    assert max(abs(e) for e in err256) <= 0.03


def test_the_stale_read_differs_from_the_right_one_by_more_than_the_noise():
    # every default signal frequency sits far enough from the *RST frequency in calibration factor
    for seed in range(60):
        sim = KX100(seed=seed)
        assert abs(sim.expected_dbm(freq_hz=50e6) - sim.expected_dbm()) > 0.12


def test_the_high_range_adds_a_larger_zero_offset_at_low_power():
    sim = KX100(seed=0, signal_hz=2e9, signal_dbm=-30.0)
    low = sim.expected_dbm(power_range="LOW")
    high = sim.expected_dbm(power_range="HIGH")
    assert abs(low - (-30.0)) < 0.005
    assert high - low > 0.05
    assert sim.expected_dbm(power_range="AUTO") == low


def test_the_low_range_over_ranges_above_minus_10_dbm():
    sim = KX100(seed=0, signal_hz=2e9, signal_dbm=-5.0)
    sim.write("CONF:POW:RANG LOW")
    assert float(sim.query("FETC?")) == RESET_READING_DBM
    sim.write("INIT")
    assert float(sim.query("FETC?")) == 9.9e37
    assert sim.query("SYST:ERR?") == '201,"Measurement over range"'


def test_readings_have_the_declared_resolution():
    sim = KX100(seed=11)
    value = _measure(sim, sim.signal_hz, 4)
    assert math.isclose(value * 100, round(value * 100), abs_tol=1e-9)


# --- determinism ---------------------------------------------------------------------------------


def _script(sim: KX100) -> list[str]:
    out = [sim.query("*IDN?")]
    for count in (1, 4, 16):
        sim.write(f"SENS:AVER:COUN {count}")
        sim.write("SENS:FREQ 9e9")
        sim.write("INIT")
        out.append(sim.query("FETC?"))
    out.append(sim.query("SYST:ERR?"))
    return out


def test_the_same_seed_gives_the_same_session():
    assert _script(KX100(seed=42)) == _script(KX100(seed=42))


def test_different_seeds_give_different_signals():
    assert KX100(seed=1).true_power_dbm != KX100(seed=2).true_power_dbm


def test_a_hidden_signal_outside_the_band_is_refused():
    with pytest.raises(ValueError):
        KX100(seed=0, signal_hz=40e9)


# --- the manual ----------------------------------------------------------------------------------


def _manual() -> str:
    return MANUAL_PATH.read_bytes().decode("utf-8")


def test_the_manual_has_lf_line_endings_and_about_120_lines():
    text = _manual()
    assert "\r" not in text
    assert 90 <= len(text.splitlines()) <= 170


@pytest.mark.parametrize("line", LIMIT_LINES)
def test_every_declared_limit_line_is_in_the_manual_verbatim_on_its_own_line(line):
    assert any(raw.strip("- ").strip() == line for raw in _manual().splitlines()), line


def test_the_limit_lines_cover_resolution_and_band():
    assert "Measurement resolution: 0.01 dB" in LIMIT_LINES
    assert "Frequency range: 10 MHz to 18 GHz" in LIMIT_LINES


@pytest.mark.parametrize("row", SPEC_TABLE_ROWS, ids=lambda r: r[0])
def test_every_specification_row_is_in_the_manual_table(row):
    assert "| " + " | ".join(row) + " |" in _manual()


@pytest.mark.parametrize("header", COMMANDS)
def test_every_command_the_simulator_accepts_is_documented(header):
    assert f"`{header}" in _manual()


def test_the_manual_states_the_dbm_to_watt_conversion_with_ten():
    text = _manual()
    assert "P_W = 10^(P_dBm / 10) / 1000" in text
    assert "/ 20" not in text
