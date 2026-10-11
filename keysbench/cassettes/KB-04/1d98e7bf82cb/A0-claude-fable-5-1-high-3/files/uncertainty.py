"""Uncertainty budget for one KX-100 reading (first-order GUM), from MANUAL.md sections 5 and 7."""

import math

# Section 6 limits.
FREQ_MIN_HZ = 10e6
FREQ_MAX_HZ = 18e9
AVERAGES_MIN = 1
AVERAGES_MAX = 1024

# Section 5 contributions (half-widths / standard deviations before dividing).
ACCURACY_PCT = 0.50  # % of reading, rectangular
LINEARITY_PCT = 0.30  # % of reading, rectangular
ZERO_OFFSET_W = {"LOW": 0.5e-9, "HIGH": 50e-9}  # ±nW, rectangular
CAL_FACTOR_PCT_LOW_BAND = 1.6  # % of reading, expanded k=2, 10 MHz to 8 GHz
CAL_FACTOR_PCT_HIGH_BAND = 2.2  # % of reading, expanded k=2, above 8 GHz to 18 GHz
NOISE_PCT_AT_N1 = 2.0  # % of reading, one standard deviation at N = 1
GAMMA_METER_LOW_BAND = 0.10  # Γm, 10 MHz to 8 GHz
GAMMA_METER_HIGH_BAND = 0.15  # Γm, above 8 GHz to 18 GHz
RESOLUTION_HALF_STEP_DB = 0.005  # dB, half of the 0.01 dB step, rectangular
BAND_SPLIT_HZ = 8e9

SQRT3 = math.sqrt(3.0)
SQRT2 = math.sqrt(2.0)


def dbm_to_watts(p_dbm: float) -> float:
    """Section 7: P_W = 10^(P_dBm / 10) / 1000."""
    return 10.0 ** (p_dbm / 10.0) / 1000.0


def absolute_to_pct(a_watts: float, p_watts: float) -> float:
    """Section 7: an absolute contribution a (W) at reading P_W is 100·a / P_W % of reading."""
    return 100.0 * a_watts / p_watts


def db_to_pct(d_db: float) -> float:
    """Section 7: a contribution d in dB is (10^(d / 10) - 1)·100 % of reading."""
    return (10.0 ** (d_db / 10.0) - 1.0) * 100.0


def combined_uncertainty_pct(
    reading_dbm: float, freq_hz: float, averages: int, power_range: str, gamma_source: float
) -> float:
    """Combined standard uncertainty u_c of one reading, in % of reading.

    reading_dbm: the reading; freq_hz: the signal frequency; averages: the averaging count N;
    power_range: "LOW" or "HIGH"; gamma_source: the source's reflection coefficient magnitude.

    u_c = sqrt(sum of (value_i / divisor_i)^2), every term in % of reading (MANUAL.md section 5).
    """
    range_key = str(power_range).strip().upper()
    if range_key not in ZERO_OFFSET_W:
        raise ValueError(f"power_range must be 'LOW' or 'HIGH', got {power_range!r}")
    if not (FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ):
        raise ValueError(f"freq_hz {freq_hz!r} is outside the 10 MHz to 18 GHz range")
    if averages < AVERAGES_MIN or averages > AVERAGES_MAX:
        raise ValueError(f"averages must be between 1 and 1024, got {averages!r}")
    if gamma_source < 0.0:
        raise ValueError(f"gamma_source must be non-negative, got {gamma_source!r}")

    reading_w = dbm_to_watts(reading_dbm)

    if freq_hz <= BAND_SPLIT_HZ:
        cal_factor_pct = CAL_FACTOR_PCT_LOW_BAND
        gamma_meter = GAMMA_METER_LOW_BAND
    else:
        cal_factor_pct = CAL_FACTOR_PCT_HIGH_BAND
        gamma_meter = GAMMA_METER_HIGH_BAND

    # Standard uncertainties, all in % of reading.
    u_accuracy = ACCURACY_PCT / SQRT3
    u_linearity = LINEARITY_PCT / SQRT3
    u_zero = absolute_to_pct(ZERO_OFFSET_W[range_key], reading_w) / SQRT3
    u_cal_factor = cal_factor_pct / 2.0
    u_noise = NOISE_PCT_AT_N1 / math.sqrt(averages) / 1.0
    u_mismatch = 200.0 * gamma_source * gamma_meter / SQRT2
    u_resolution = db_to_pct(RESOLUTION_HALF_STEP_DB) / SQRT3

    terms = (
        u_accuracy,
        u_linearity,
        u_zero,
        u_cal_factor,
        u_noise,
        u_mismatch,
        u_resolution,
    )
    return float(math.sqrt(sum(t * t for t in terms)))
