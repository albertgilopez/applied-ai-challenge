"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    sqrt2 = math.sqrt(2.0)
    sqrt3 = math.sqrt(3.0)

    # Section 7: reading in watts (dBm -> W).
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0

    # Frequency band: "10 MHz to 8 GHz" (8 GHz inclusive) or "above 8 GHz to 18 GHz".
    low_band = freq_hz <= 8.0e9

    # Instrument accuracy: ±0.50 % of reading, rectangular, /√3.
    u_accuracy = 0.50 / sqrt3

    # Linearity: ±0.30 % of reading, rectangular, /√3.
    u_linearity = 0.30 / sqrt3

    # Zero offset: ±0.5 nW (LOW) or ±50 nW (HIGH), rectangular, /√3.
    # Absolute contribution a (W) at reading P_W is 100·a / P_W % of reading.
    rng = power_range.strip().upper()
    if rng == "LOW":
        zero_w = 0.5e-9
    elif rng == "HIGH":
        zero_w = 50e-9
    else:
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    u_zero = (100.0 * zero_w / p_w) / sqrt3

    # Calibration factor: ±1.6 % (≤ 8 GHz) or ±2.2 % (> 8 GHz), expanded k = 2, normal, /2.
    u_calfactor = (1.6 if low_band else 2.2) / 2.0

    # Noise: 2.0 / √N % of reading, one standard deviation, /1.
    u_noise = 2.0 / math.sqrt(averages)

    # Mismatch: ±200·Γs·Γm % of reading, U-shaped, /√2. Γm = 0.10 (≤ 8 GHz) or 0.15 (> 8 GHz).
    gamma_meter = 0.10 if low_band else 0.15
    u_mismatch = (200.0 * gamma_source * gamma_meter) / sqrt2

    # Display resolution: ±0.005 dB, rectangular, /√3; d dB is (10^(d/10) - 1)·100 % of reading.
    res_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0
    u_resolution = res_pct / sqrt3

    terms = (
        u_accuracy,
        u_linearity,
        u_zero,
        u_calfactor,
        u_noise,
        u_mismatch,
        u_resolution,
    )
    return float(math.sqrt(sum(t * t for t in terms)))
