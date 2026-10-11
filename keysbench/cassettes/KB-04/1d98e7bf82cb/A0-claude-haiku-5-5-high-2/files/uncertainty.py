"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.

    Raises ValueError for inputs the instrument cannot measure (MANUAL.md sections 2 and 6).
    """
    reading = float(reading_dbm)
    freq = float(freq_hz)
    rng = str(power_range).strip().upper()
    gamma_s = float(gamma_source)

    # Validation against the stated limits.
    if not (10e6 <= freq <= 18e9):
        raise ValueError("frequency outside 10 MHz to 18 GHz")
    if averages != int(averages) or not (1 <= int(averages) <= 1024):
        raise ValueError("averaging count must be an integer from 1 to 1024")
    n = int(averages)
    if rng == "LOW":
        if not (-60.0 <= reading <= -10.0):
            raise ValueError("reading outside the LOW range (-60 to -10 dBm)")
    elif rng == "HIGH":
        if not (-30.0 <= reading <= 20.0):
            raise ValueError("reading outside the HIGH range (-30 to +20 dBm)")
    else:
        raise ValueError("power_range must be LOW or HIGH")
    if not (0.0 <= gamma_s <= 1.0):
        raise ValueError("reflection coefficient magnitude must be in [0, 1]")

    # Reading in watts (section 7).
    p_w = 10.0 ** (reading / 10.0) / 1000.0

    # Frequency-dependent items: 8 GHz belongs to the lower band (section 5 "10 MHz to 8 GHz").
    if freq <= 8e9:
        cf_value_pct, gamma_m = 1.6, 0.10
    else:
        cf_value_pct, gamma_m = 2.2, 0.15

    # Standard uncertainties, all in % of reading.
    u_accuracy = 0.50 / math.sqrt(3.0)
    u_linearity = 0.30 / math.sqrt(3.0)

    zero_nw = 0.5 if rng == "LOW" else 50.0
    u_zero = 100.0 * (zero_nw * 1e-9 / math.sqrt(3.0)) / p_w

    u_cal = cf_value_pct / 2.0
    u_noise = 2.0 / math.sqrt(n)
    u_mismatch = 200.0 * gamma_s * gamma_m / math.sqrt(2.0)

    # Display resolution: half of 0.01 dB = 0.005 dB, rectangular, converted by section 7.
    res_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0
    u_resolution = res_pct / math.sqrt(3.0)

    terms = (u_accuracy, u_linearity, u_zero, u_cal, u_noise, u_mismatch, u_resolution)
    return math.sqrt(sum(t * t for t in terms))
