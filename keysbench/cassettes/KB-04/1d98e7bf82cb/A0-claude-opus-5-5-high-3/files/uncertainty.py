"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math
import numbers

# Instrument limits (MANUAL.md sections 2 and 6).
_FREQ_MIN_HZ = 10e6
_FREQ_MAX_HZ = 18e9
_CF_BAND_EDGE_HZ = 8e9  # "10 MHz to 8 GHz" / "above 8 GHz to 18 GHz"
_AVER_MIN = 1
_AVER_MAX = 1024
_POWER_MIN_DBM = -60.0
_POWER_MAX_DBM = 20.0
_LOW_RANGE_MAX_DBM = -10.0  # above this LOW over-ranges (error 201, no valid reading)

_SQRT3 = math.sqrt(3.0)
_SQRT2 = math.sqrt(2.0)


def _is_real_number(x) -> bool:
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.

    Raises ValueError for inputs outside what the instrument can measure (MANUAL.md sections 2
    and 6), since no calibrated reading -- and so no budget -- exists for them.
    """
    # ---- validation -------------------------------------------------------------------------
    if not _is_real_number(reading_dbm):
        raise ValueError(f"reading_dbm must be a finite number, got {reading_dbm!r}")
    if not _is_real_number(freq_hz):
        raise ValueError(f"freq_hz must be a finite number, got {freq_hz!r}")
    if not _is_real_number(gamma_source):
        raise ValueError(f"gamma_source must be a finite number, got {gamma_source!r}")

    if isinstance(averages, bool) or not isinstance(averages, numbers.Real):
        raise ValueError(f"averages must be an integer, got {averages!r}")
    if isinstance(averages, numbers.Integral):
        n = int(averages)
    elif math.isfinite(averages) and float(averages).is_integer():
        n = int(averages)
    else:
        raise ValueError(f"averages must be an integer, got {averages!r}")
    if not _AVER_MIN <= n <= _AVER_MAX:
        raise ValueError(f"averages must be in {_AVER_MIN}..{_AVER_MAX}, got {n}")

    if not isinstance(power_range, str):
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    rng = power_range.strip().upper()
    if rng not in ("LOW", "HIGH"):
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")

    if not _FREQ_MIN_HZ <= freq_hz <= _FREQ_MAX_HZ:
        raise ValueError(f"freq_hz {freq_hz!r} outside the 10 MHz to 18 GHz band")

    if not _POWER_MIN_DBM <= reading_dbm <= _POWER_MAX_DBM:
        raise ValueError(f"reading_dbm {reading_dbm!r} outside the -60 dBm to +20 dBm power range")
    if rng == "LOW" and reading_dbm > _LOW_RANGE_MAX_DBM:
        raise ValueError(f"reading_dbm {reading_dbm!r} over-ranges the LOW range (max -10 dBm)")

    if not 0.0 <= gamma_source <= 1.0:
        raise ValueError(f"gamma_source must be in [0, 1], got {gamma_source!r}")

    # ---- budget (all standard uncertainties in % of reading) ----------------------------------
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0  # section 7: dBm -> W
    upper_band = freq_hz > _CF_BAND_EDGE_HZ

    u_accuracy = 0.50 / _SQRT3
    u_linearity = 0.30 / _SQRT3

    zero_w = 0.5e-9 if rng == "LOW" else 50e-9
    u_zero = (100.0 * zero_w / p_w) / _SQRT3  # absolute -> % of reading

    u_cal = (2.2 if upper_band else 1.6) / 2.0

    u_noise = 2.0 / math.sqrt(n)

    gamma_m = 0.15 if upper_band else 0.10
    u_mismatch = (200.0 * gamma_source * gamma_m) / _SQRT2

    resolution_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0  # dB -> % of reading (~0.115 %)
    u_resolution = resolution_pct / _SQRT3

    terms = (
        u_accuracy,
        u_linearity,
        u_zero,
        u_cal,
        u_noise,
        u_mismatch,
        u_resolution,
    )
    return float(math.sqrt(sum(t * t for t in terms)))
