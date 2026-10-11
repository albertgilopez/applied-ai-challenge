"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.
    """
    import math

    if averages < 1:
        raise ValueError("averages must be >= 1")
    rng = str(power_range).strip().upper()
    if rng not in ("LOW", "HIGH"):
        raise ValueError('power_range must be "LOW" or "HIGH"')

    sqrt3 = math.sqrt(3.0)
    sqrt2 = math.sqrt(2.0)

    # Section 7: reading in watts, for the absolute (nW) contribution.
    p_w = 10.0 ** (reading_dbm / 10.0) / 1000.0

    # Instrument accuracy: ±0.50 % of reading, rectangular.
    u_accuracy = 0.50 / sqrt3

    # Linearity: ±0.30 % of reading, rectangular.
    u_linearity = 0.30 / sqrt3

    # Zero offset: ±0.5 nW (LOW) or ±50 nW (HIGH), rectangular; a (W) -> 100*a/P_W %.
    zero_nw = 0.5 if rng == "LOW" else 50.0
    zero_pct = 100.0 * (zero_nw * 1e-9) / p_w
    u_zero = zero_pct / sqrt3

    # Calibration factor (expanded k=2, normal) and sensor reflection coefficient
    # depend on the frequency band: 10 MHz..8 GHz inclusive, or above 8 GHz..18 GHz.
    if freq_hz <= 8e9:
        cal_factor_pct = 1.6
        gamma_meter = 0.10
    else:
        cal_factor_pct = 2.2
        gamma_meter = 0.15
    u_cal = cal_factor_pct / 2.0

    # Noise: 2.0/sqrt(N) % of reading, already one standard deviation.
    u_noise = 2.0 / math.sqrt(averages) / 1.0

    # Mismatch: ±200*Gs*Gm % of reading, U-shaped, divisor sqrt(2).
    u_mismatch = 200.0 * gamma_source * gamma_meter / sqrt2

    # Display resolution: ±0.005 dB, rectangular; d dB -> (10^(d/10) - 1)*100 %.
    resolution_pct = (10.0 ** (0.005 / 10.0) - 1.0) * 100.0
    u_resolution = resolution_pct / sqrt3

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
