"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    import math

    rng = str(power_range).strip().upper()
    if rng not in ("LOW", "HIGH"):
        raise ValueError("power_range must be 'LOW' or 'HIGH'")
    if not (10e6 <= freq_hz <= 18e9):
        raise ValueError("frequency outside 10 MHz to 18 GHz")
    if int(averages) != averages or not (1 <= averages <= 1024):
        raise ValueError("averages must be an integer from 1 to 1024")
    if not (-60.0 <= reading_dbm <= 20.0):
        raise ValueError("reading outside -60 dBm to +20 dBm")
    if rng == "LOW" and reading_dbm > -10.0:
        raise ValueError("input above -10 dBm over-ranges the LOW range")
    if not (0.0 <= gamma_source <= 1.0):
        raise ValueError("gamma_source must be between 0 and 1")

    sqrt3 = math.sqrt(3.0)
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0

    low_band = freq_hz <= 8e9
    cal_expanded = 1.6 if low_band else 2.2
    gamma_m = 0.10 if low_band else 0.15
    zero_w = 0.5e-9 if rng == "LOW" else 50e-9

    terms = [
        0.50 / sqrt3,                                   # instrument accuracy
        0.30 / sqrt3,                                   # linearity
        (100.0 * zero_w / p_w) / sqrt3,                 # zero offset
        cal_expanded / 2.0,                             # calibration factor
        2.0 / math.sqrt(averages),                      # noise
        (200.0 * gamma_source * gamma_m) / math.sqrt(2.0),  # mismatch
        ((10.0 ** (0.005 / 10.0) - 1.0) * 100.0) / sqrt3,   # display resolution
    ]
    return float(math.sqrt(sum(t * t for t in terms)))
