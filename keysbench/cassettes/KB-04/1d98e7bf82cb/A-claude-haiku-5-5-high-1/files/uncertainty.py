"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math
from numbers import Integral

_F_MIN_HZ = 10e6
_F_MAX_HZ = 18e9
_F_BOUNDARY_HZ = 8e9  # 10 MHz..8 GHz lower band; above 8 GHz to 18 GHz upper band
_P_MIN_DBM = -60.0  # whole instrument span
_P_MAX_DBM = 20.0
_LOW_MAX_DBM = -10.0  # LOW over-ranges above this
_HIGH_MIN_DBM = -30.0  # HIGH invalid below this (zero offset dominates)
_N_MIN, _N_MAX = 1, 1024


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    # --- validate inputs against the instrument limits (MANUAL sections 2, 5, 6) ---
    p_dbm = float(reading_dbm)
    if not (_P_MIN_DBM <= p_dbm <= _P_MAX_DBM):
        raise ValueError(f"reading {p_dbm} dBm outside instrument span -60..+20 dBm")

    f = float(freq_hz)
    if not (_F_MIN_HZ <= f <= _F_MAX_HZ):
        raise ValueError(f"frequency {f} Hz outside 10 MHz..18 GHz")

    if isinstance(averages, bool) or not isinstance(averages, Integral):
        raise TypeError("averages must be an integer")
    n = int(averages)
    if not (_N_MIN <= n <= _N_MAX):
        raise ValueError(f"averages {n} outside 1..1024")

    rng = str(power_range).strip().upper()
    if rng not in ("LOW", "HIGH"):
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    if rng == "LOW" and p_dbm > _LOW_MAX_DBM:
        raise ValueError(f"reading {p_dbm} dBm over-ranges LOW (above -10 dBm)")
    if rng == "HIGH" and p_dbm < _HIGH_MIN_DBM:
        raise ValueError(f"reading {p_dbm} dBm below HIGH range (-30 dBm)")

    gs = float(gamma_source)
    if not (0.0 <= gs <= 1.0):
        raise ValueError("gamma_source must be a reflection coefficient magnitude in 0..1")

    # --- reading in watts (section 7) ---
    p_w = 10.0 ** (p_dbm / 10.0) / 1000.0

    # --- frequency-band-dependent values (sections 4 and 5) ---
    upper_band = f > _F_BOUNDARY_HZ
    cal_expanded_pct = 2.2 if upper_band else 1.6  # expanded, k = 2, normal
    gamma_m = 0.15 if upper_band else 0.10

    # --- standard uncertainties, each in % of reading ---
    # Rectangular distributions: divisor sqrt(3).
    s_accuracy = 0.50 / math.sqrt(3.0)
    s_linearity = 0.30 / math.sqrt(3.0)

    # Zero offset: absolute power in nW, converted to % of reading (section 7).
    zero_nw = 0.5 if rng == "LOW" else 50.0
    s_zero = 100.0 * (zero_nw * 1e-9 / math.sqrt(3.0)) / p_w

    # Calibration factor: expanded k = 2, normal -> divisor 2.
    s_cal = cal_expanded_pct / 2.0

    # Noise: 2.0 / sqrt(N) % one standard deviation.
    s_noise = 2.0 / math.sqrt(n)

    # Mismatch: U-shaped, divisor sqrt(2); limit ±200 * Gs * Gm %.
    s_mismatch = 200.0 * gs * gamma_m / math.sqrt(2.0)

    # Display resolution: ±0.005 dB rectangular; convert the dB half-width to % first (section 7).
    res_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0
    s_res = res_pct / math.sqrt(3.0)

    u_c = math.sqrt(
        s_accuracy**2
        + s_linearity**2
        + s_zero**2
        + s_cal**2
        + s_noise**2
        + s_mismatch**2
        + s_res**2
    )
    return float(u_c)
