"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math
import numbers

# Section 2 / 6 limits
_FREQ_MIN_HZ = 10e6
_FREQ_MAX_HZ = 18e9
_CF_BAND_EDGE_HZ = 8e9  # "10 MHz to 8 GHz" inclusive, "above 8 GHz to 18 GHz"
_AVER_MIN = 1
_AVER_MAX = 1024
_RANGE_LIMITS_DBM = {"LOW": (-60.0, -10.0), "HIGH": (-30.0, 20.0)}
_POWER_MIN_DBM = -60.0  # section 6: the instrument cannot measure below this

# Section 5 specifications: (half-width or value, divisor)
_SQRT3 = math.sqrt(3.0)
_SQRT2 = math.sqrt(2.0)
_ACCURACY_PCT = 0.50
_LINEARITY_PCT = 0.30
_ZERO_OFFSET_W = {"LOW": 0.5e-9, "HIGH": 50e-9}
_CF_EXPANDED_PCT_LOW_BAND = 1.6
_CF_EXPANDED_PCT_HIGH_BAND = 2.2
_CF_K = 2.0
_NOISE_PCT_N1 = 2.0
_GAMMA_M_LOW_BAND = 0.10
_GAMMA_M_HIGH_BAND = 0.15
_RESOLUTION_HALF_STEP_DB = 0.005


def _finite_real(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return value


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.

    Raises ValueError (or TypeError) for inputs the KX-100 cannot produce a calibrated reading
    with: frequency outside 10 MHz to 18 GHz, averaging count outside 1 to 1024, a range other
    than LOW/HIGH, a reading outside the selected range (over-range on LOW, below -60 dBm, the
    +9.90E+37 over-range marker), or |Gamma_s| outside 0 to 1.
    """
    reading_dbm = _finite_real("reading_dbm", reading_dbm)
    freq_hz = _finite_real("freq_hz", freq_hz)
    gamma_source = _finite_real("gamma_source", gamma_source)

    # Averaging count: integer 1..1024
    if isinstance(averages, bool):
        raise TypeError(f"averages must be an integer, got {averages!r}")
    if isinstance(averages, numbers.Integral):
        n = int(averages)
    elif isinstance(averages, numbers.Real) and float(averages).is_integer():
        n = int(averages)
    else:
        raise TypeError(f"averages must be an integer, got {averages!r}")
    if not _AVER_MIN <= n <= _AVER_MAX:
        raise ValueError(f"averages must be {_AVER_MIN} to {_AVER_MAX}, got {n}")

    # Range: LOW or HIGH (AUTO is not a fixed range, so the zero offset would be ambiguous)
    if not isinstance(power_range, str):
        raise TypeError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    rng = power_range.strip().upper()
    if rng not in _RANGE_LIMITS_DBM:
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")

    if not _FREQ_MIN_HZ <= freq_hz <= _FREQ_MAX_HZ:
        raise ValueError(f"freq_hz must be 10 MHz to 18 GHz, got {freq_hz!r}")

    if not 0.0 <= gamma_source <= 1.0:
        raise ValueError(f"gamma_source must be 0 to 1, got {gamma_source!r}")

    # Reading: within the instrument's power limits and not over-ranged on the selected range.
    low_dbm, high_dbm = _RANGE_LIMITS_DBM[rng]
    if reading_dbm > high_dbm:
        raise ValueError(f"reading {reading_dbm} dBm is over range for {rng} (max {high_dbm} dBm)")
    if reading_dbm < _POWER_MIN_DBM:
        raise ValueError(f"reading {reading_dbm} dBm is below the instrument limit of -60 dBm")
    # HIGH below -30 dBm is still a reading; its zero-offset term simply dominates the budget.

    # Section 7 conversion
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0

    high_band = freq_hz > _CF_BAND_EDGE_HZ
    cf_expanded = _CF_EXPANDED_PCT_HIGH_BAND if high_band else _CF_EXPANDED_PCT_LOW_BAND
    gamma_m = _GAMMA_M_HIGH_BAND if high_band else _GAMMA_M_LOW_BAND

    resolution_pct = (10.0 ** (_RESOLUTION_HALF_STEP_DB / 10.0) - 1.0) * 100.0

    standard_uncertainties = (
        _ACCURACY_PCT / _SQRT3,
        _LINEARITY_PCT / _SQRT3,
        (100.0 * _ZERO_OFFSET_W[rng] / p_w) / _SQRT3,
        cf_expanded / _CF_K,
        _NOISE_PCT_N1 / math.sqrt(n),
        (200.0 * gamma_source * gamma_m) / _SQRT2,
        resolution_pct / _SQRT3,
    )
    return float(math.sqrt(sum(u * u for u in standard_uncertainties)))
