"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math

# Instrument limits (MANUAL.md section 6 and section 2).
_FREQ_MIN_HZ = 10e6
_FREQ_MAX_HZ = 18e9
_AVG_MIN = 1
_AVG_MAX = 1024
_RANGE_LIMITS_DBM = {"LOW": (-60.0, -10.0), "HIGH": (-30.0, 20.0)}
_GAMMA_MAX = 1.0


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.

    Raises ValueError for inputs the instrument cannot measure with a calibrated result.
    """
    reading = float(reading_dbm)
    freq = float(freq_hz)
    rng = str(power_range).upper()
    gamma_s = float(gamma_source)

    if not (_FREQ_MIN_HZ <= freq <= _FREQ_MAX_HZ):
        raise ValueError(f"frequency {freq} Hz outside 10 MHz to 18 GHz")
    if int(averages) != averages or not (_AVG_MIN <= int(averages) <= _AVG_MAX):
        raise ValueError(f"averaging count {averages} outside integer 1 to 1024")
    n = int(averages)
    if rng not in _RANGE_LIMITS_DBM:
        raise ValueError(f"power_range must be LOW or HIGH, got {power_range!r}")
    lo, hi = _RANGE_LIMITS_DBM[rng]
    if not (lo <= reading <= hi):
        raise ValueError(f"reading {reading} dBm outside {rng} range {lo} to {hi} dBm")
    if not (0.0 <= gamma_s <= _GAMMA_MAX):
        raise ValueError(f"reflection coefficient {gamma_s} outside 0 to 1")

    sqrt2 = math.sqrt(2.0)
    sqrt3 = math.sqrt(3.0)
    low_band = freq <= 8e9  # 10 MHz to 8 GHz inclusive; above 8 GHz to 18 GHz otherwise

    # Reading power in watts (section 7), used to turn absolute contributions into % of reading.
    p_w = 10.0 ** (reading / 10.0) / 1000.0

    # Each entry: value in % of reading (before the divisor), divisor.
    terms = []

    # Instrument accuracy, ±0.50 % of reading, rectangular.
    terms.append((0.50, sqrt3))

    # Linearity, ±0.30 % of reading, rectangular.
    terms.append((0.30, sqrt3))

    # Zero offset, absolute, rectangular: ±0.5 nW (LOW) or ±50 nW (HIGH).
    zero_w = 0.5e-9 if rng == "LOW" else 50e-9
    terms.append((100.0 * zero_w / p_w, sqrt3))

    # Calibration factor uncertainty, expanded (k = 2), normal: divisor 2.
    terms.append((1.6 if low_band else 2.2, 2.0))

    # Noise, one standard deviation, 2.0 / sqrt(N) % of reading.
    terms.append((2.0 / math.sqrt(n), 1.0))

    # Mismatch, U-shaped: ±200 * Γs * Γm % of reading, divisor sqrt(2).
    gamma_m = 0.10 if low_band else 0.15
    terms.append((200.0 * gamma_s * gamma_m, sqrt2))

    # Display resolution: ±0.005 dB, rectangular; converted to % of reading first (section 7).
    res_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0
    terms.append((res_pct, sqrt3))

    return float(math.sqrt(sum((value / divisor) ** 2 for value, divisor in terms)))
