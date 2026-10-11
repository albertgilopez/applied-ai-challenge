# Review of change to power.py

**Verdict: do not approve (request changes).** There is one definite bug, and it makes both new helpers return wrong numbers.

## 1. Blocking: `dbm_to_watts` uses the wrong exponent (power.py, line 13)

```python
return 10 ** (dbm / 20) / 1000      # wrong
```

The divisor should be 10, not 20. MANUAL.md section 7 gives the conversion as
`P_W = 10^(P_dBm / 10) / 1000`. A divisor of 20 is the conversion for a voltage or
amplitude ratio. A power reading in dBm is a power ratio, so 10 is correct.

Effect:
- 0 dBm gives 1 mW either way, so a quick check at 0 dBm will not show the bug.
- Every other value is wrong. +10 dBm returns 3.16 mW instead of 10 mW. -30 dBm returns
  about 31.6 nW instead of 1 µW. In dB terms the result is off by a factor of two.
- `mean_power_dbm` inherits this. It converts back with the correct `10·log10(1000·P)`, so the
  round trip does not cancel the error. The mean of any set of identical readings comes out as
  half the reading: `mean_power_dbm([10.0, 10.0])` returns +5.0 instead of +10.0, and
  `mean_power_dbm([-40.0])` returns -20.0. For the meter's range of -60 to +20 dBm this is up to
  30 dB off.

Fix: `return 10 ** (dbm / 10) / 1000`.

## 2. Should fix: `mean_power_dbm` fails on an empty list and on invalid readings

- An empty list raises `ZeroDivisionError`. Raise a clear `ValueError`, or define the behaviour
  explicitly.
- The manual says a `FETC?` value is not valid in some cases, and these values can reach this
  function:
  - A LOW-range over-range returns the sentinel `+9.90E+37` (with error 201). In
    `dbm_to_watts`, `10 ** (9.9e37 / 10)` raises `OverflowError`. With the sentinel
    handled differently it would still not be a power.
  - `*RST` or power-on returns the reset reading of -100.00 dBm. This is below the instrument's
    -60 dBm limit and is not a measurement.
  - The docstring should say that callers must pass only valid readings (section 3 step 8: error
    queue clear). It would be better to reject values outside -60..+20 dBm, or to document that
    the caller filters them.

## 3. Minor

- There are no tests. A test for `dbm_to_watts` at 0, +10, -30 and +20 dBm (1 mW, 10 mW, 1 µW,
  100 mW) would have caught the bug in item 1. Add a round-trip test, `mean_power_dbm([x, x]) == x`
  (using `pytest.approx`), and a test for the mean of two different values, for example
  `mean_power_dbm([0, 10])` ≈ +7.40 dBm.
- The result has more precision than the meter's 0.01 dB resolution (section 6). This is fine for
  an internal mean, but do not present it as a finer reading. Use `format_reading` for logging.
- `list[float]` needs Python 3.9 or newer. Confirm that this is the project's minimum.

## Summary

Averaging in the linear domain is the right approach, and the `mean_power_dbm` formula itself is
correct. The change is blocked by the `/20` error in `dbm_to_watts`. Please fix it, add tests, and
handle empty or invalid input. I will re-review after that.

