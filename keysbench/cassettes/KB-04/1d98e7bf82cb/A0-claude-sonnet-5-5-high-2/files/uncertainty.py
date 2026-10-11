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
        raise ValueError("input over-ranges the LOW range (above -10 dBm)")
    if not (0.0 <= gamma_source <= 1.0):
        raise ValueError("gamma_source must be between 0 and 1")

    p_w = 10 ** (reading_dbm / 10) / 1000
    sqrt3 = math.sqrt(3)

    accuracy = 0.50 / sqrt3
    linearity = 0.30 / sqrt3

    zero_w = 0.5e-9 if rng == "LOW" else 50e-9
    zero = (100 * zero_w / p_w) / sqrt3

    if freq_hz <= 8e9:
        cal = 1.6 / 2
        gamma_m = 0.10
    else:
        cal = 2.2 / 2
        gamma_m = 0.15

    noise = 2.0 / math.sqrt(averages)
    mismatch = 200 * gamma_source * gamma_m / math.sqrt(2)
    resolution = ((10 ** (0.005 / 10) - 1) * 100) / sqrt3

    terms = (accuracy, linearity, zero, cal, noise, mismatch, resolution)
    return float(math.sqrt(sum(t * t for t in terms)))
