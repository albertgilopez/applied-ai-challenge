"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    p_w = 10 ** (reading_dbm / 10) / 1000
    high_band = freq_hz > 8e9
    zero_w = 0.5e-9 if power_range == "LOW" else 50e-9
    gamma_meter = 0.15 if high_band else 0.10
    terms = [
        0.50 / math.sqrt(3),  # instrument accuracy
        0.30 / math.sqrt(3),  # linearity
        100 * zero_w / p_w / math.sqrt(3),  # zero offset, converted to % of reading
        (2.2 if high_band else 1.6) / 2,  # calibration factor, expanded k = 2
        2.0 / math.sqrt(averages),  # noise, one standard deviation
        200 * gamma_source * gamma_meter / math.sqrt(2),  # mismatch, U-shaped
        (10 ** (0.005 / 10) - 1) * 100 / math.sqrt(3),  # display resolution, half of 0.01 dB
    ]
    return math.sqrt(sum(t * t for t in terms))
