"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    # --- Validate inputs against the instrument's limits (MANUAL sections 2 and 6) -------------
    reading_dbm = _finite(reading_dbm, "reading_dbm")
    freq_hz = _finite(freq_hz, "freq_hz")
    gamma_source = _finite(gamma_source, "gamma_source")

    if not FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ:
        raise ValueError(
            f"freq_hz={freq_hz!r} is outside the KX-100 frequency range 10 MHz to 18 GHz"
        )

    if isinstance(averages, bool):
        raise TypeError("averages must be an integer, not a bool")
    try:
        n_float = float(averages)
    except (TypeError, ValueError):
        raise TypeError(f"averages must be an integer, got {averages!r}") from None
    if not math.isfinite(n_float) or n_float != int(n_float):
        raise ValueError(f"averages must be an integer, got {averages!r}")
    n = int(n_float)
    if not AVER_MIN <= n <= AVER_MAX:
        raise ValueError(f"averages={n} is outside the allowed count 1 to 1024")

    if not isinstance(power_range, str):
        raise TypeError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    rng = power_range.strip().upper()
    if rng not in RANGES_DBM:
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    lo, hi = RANGES_DBM[rng]
    if not lo <= reading_dbm <= hi:
        raise ValueError(
            f"reading_dbm={reading_dbm!r} is outside the {rng} range ({lo:+g} dBm to {hi:+g} dBm); "
            "the reading is over-ranged or not a valid measurement on that range"
        )

    if not 0.0 <= gamma_source <= 1.0:
        raise ValueError(f"gamma_source={gamma_source!r} must be a magnitude between 0 and 1")

    # --- Budget (MANUAL section 5), every term as a standard uncertainty in % of reading ------
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0  # section 7: dBm -> W
    high_band = freq_hz > BAND_SPLIT_HZ  # "above 8 GHz" belongs to the upper band

    zero_offset_w = ZERO_OFFSET_W[rng]
    cal_factor_expanded = 2.2 if high_band else 1.6
    gamma_m = 0.15 if high_band else 0.10
    resolution_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0  # section 7: 0.005 dB -> 0.115 %

    terms = (
        0.50 / SQRT3,  # instrument accuracy, rectangular
        0.30 / SQRT3,  # linearity, rectangular
        (100.0 * zero_offset_w / p_w) / SQRT3,  # zero offset (absolute -> % of reading), rect.
        cal_factor_expanded / 2.0,  # calibration factor, expanded k = 2, normal
        2.0 / math.sqrt(n),  # noise, already one standard deviation
        (200.0 * gamma_source * gamma_m) / SQRT2,  # mismatch, U-shaped
        resolution_pct / SQRT3,  # display resolution, rectangular
    )
    return float(math.sqrt(sum(t * t for t in terms)))


SQRT2 = math.sqrt(2.0)
SQRT3 = math.sqrt(3.0)

FREQ_MIN_HZ = 10e6
FREQ_MAX_HZ = 18e9
BAND_SPLIT_HZ = 8e9

AVER_MIN = 1
AVER_MAX = 1024

# Specified span of each fixed range, in dBm (MANUAL section 2, "Ranges").
RANGES_DBM = {"LOW": (-60.0, -10.0), "HIGH": (-30.0, 20.0)}

# Zero offset limits, in W (MANUAL section 5).
ZERO_OFFSET_W = {"LOW": 0.5e-9, "HIGH": 50e-9}


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number, not a bool")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise TypeError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return x
