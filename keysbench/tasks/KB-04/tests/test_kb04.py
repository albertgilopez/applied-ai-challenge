"""Hidden tests for KB-04: the combined standard uncertainty at three readings, 0.5 % relative tolerance.

The reference values were computed once from MANUAL.md sections 5 and 7 (root-sum-square of every
contribution, each divided by its divisor, nW and dB converted to % of reading at the reading).
"""

from kbcall import call

TOLERANCE = 0.005  # relative

# reading dBm, frequency Hz, averaging count, range, source reflection coefficient -> u_c in %
REFERENCE = [
    ((-20.0, 2.0e9, 16, "LOW", 0.05), 1.2279),  # the calibration factor dominates
    ((-45.0, 12.0e9, 4, "LOW", 0.2), 4.6001),  # mismatch and zero offset dominate, upper band
    ((5.0, 6.0e9, 64, "HIGH", 0.1), 1.6794),  # high power on the HIGH range
]


def u_c(args: tuple) -> object:
    return call(f"uncertainty.combined_uncertainty_pct(*{args!r})", "uncertainty")


def test_reference_reading_low_range():
    args, expected = REFERENCE[0]
    got = u_c(args)
    assert type(got) is float and abs(got - expected) <= TOLERANCE * expected, got


def test_reference_reading_upper_band():
    args, expected = REFERENCE[1]
    got = u_c(args)
    assert type(got) is float and abs(got - expected) <= TOLERANCE * expected, got


def test_reference_reading_high_range():
    args, expected = REFERENCE[2]
    got = u_c(args)
    assert type(got) is float and abs(got - expected) <= TOLERANCE * expected, got
