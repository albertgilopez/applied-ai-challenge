"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    # Validate against the instrument limits (MANUAL.md sections 2, 5 and 6).
    rng = str(power_range).strip().upper()
    if rng not in ("LOW", "HIGH"):
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    if not (10e6 <= freq_hz <= 18e9):
        raise ValueError(f"freq_hz {freq_hz} outside 10 MHz to 18 GHz")
    if isinstance(averages, bool) or not isinstance(averages, int) or not (1 <= averages <= 1024):
        raise ValueError(f"averages must be an integer 1 to 1024, got {averages!r}")
    if not (0.0 <= gamma_source <= 1.0):
        raise ValueError(f"gamma_source {gamma_source} outside 0 to 1")
    # Each range's span (section 2): LOW -60..-10 dBm (over-range above -10), HIGH -30..+20 dBm.
    lo, hi = (-60.0, -10.0) if rng == "LOW" else (-30.0, 20.0)
    if not (lo <= reading_dbm <= hi):
        raise ValueError(f"reading {reading_dbm} dBm outside {rng} range {lo} to {hi} dBm")

    sqrt2 = math.sqrt(2.0)
    sqrt3 = math.sqrt(3.0)
    low_band = freq_hz <= 8e9  # 10 MHz to 8 GHz inclusive; above 8 GHz to 18 GHz otherwise

    # Power in watts at the reading (section 7), for the absolute zero-offset term.
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0

    terms = []  # standard uncertainties, % of reading
    # Instrument accuracy: ±0.50 % rectangular.
    terms.append(0.50 / sqrt3)
    # Linearity: ±0.30 % rectangular.
    terms.append(0.30 / sqrt3)
    # Zero offset: absolute, nW, rectangular -> % of reading.
    zero_nw = 0.5 if rng == "LOW" else 50.0
    zero_w = zero_nw * 1e-9 / sqrt3
    terms.append(100.0 * zero_w / p_w)
    # Calibration factor: ±1.6 % or ±2.2 % expanded (k = 2), normal.
    cf_expanded = 1.6 if low_band else 2.2
    terms.append(cf_expanded / 2.0)
    # Noise: 2.0 / sqrt(N) % one standard deviation.
    terms.append(2.0 / math.sqrt(averages))
    # Mismatch: ±200 * Gs * Gm %, U-shaped.
    gamma_m = 0.10 if low_band else 0.15
    terms.append(200.0 * gamma_source * gamma_m / sqrt2)
    # Display resolution: ±0.005 dB rectangular, converted to % before dividing.
    res_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0
    terms.append(res_pct / sqrt3)

    return math.sqrt(sum(t * t for t in terms))
