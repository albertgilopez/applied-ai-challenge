# Review

**Verdict: do not approve.** `dbm_to_watts` uses the wrong exponent, so both new helpers return wrong
results for every reading except 0 dBm. The change also has no tests, which is how this got through.

## 1. Blocking: wrong dBm-to-watts conversion (`power.py`, `dbm_to_watts`)

The diff has:

```python
return 10 ** (dbm / 20) / 1000
```

The manual (section 7) gives `P_W = 10^(P_dBm / 10) / 1000`. The divisor is 20 where it must be 10.
Power in dBm is 10·log10 of the ratio, so the exponent has to be dBm/10. Using dBm/20 computes the
square root of the power, i.e. a field-like quantity, not power.

Effect (checked by hand against the formulas):

- `dbm_to_watts(-30)` returns 3.16e-5 W; the correct value is 1.00e-6 W (31.6 times too large).
- `mean_power_dbm([x])` for any single reading returns `x / 2`. For example `mean_power_dbm([-30])`
  gives -15.00 dBm.
- `mean_power_dbm([-20, -30])` gives -11.82 dBm; the correct linear mean is -22.60 dBm.
- The bug is invisible at 0 dBm (`10**0 == 10**(0/20)`), so a spot check at 0 dBm passes. That is
  probably why it was missed; any test at a non-zero level exposes it.

Fix: `return 10 ** (dbm / 10) / 1000`. Nothing else in `mean_power_dbm` needs to change: averaging
in the linear domain and converting back with `10 * log10(1000 * mean_W)` matches manual section 7.

## 2. Tests are missing

The change adds numeric code with no tests. Add tests with known values, at least:

- `dbm_to_watts(0) == 0.001` and `dbm_to_watts(-30) == 1e-6` (within float tolerance).
- `mean_power_dbm([-30.0]) == -30.0` (a single reading must round-trip).
- `mean_power_dbm([-20.0, -30.0])` ≈ -22.60 (linear average, not the arithmetic mean of dBm, which
  would be -25.00).
- `mean_power_dbm([-25.0, -25.0, -25.0]) == -25.0` (identical readings give the same value).

## 3. Input validation (should fix before merge)

Both helpers accept any list of floats. The manual says a reading is not valid when an error is
queued (section 3, step 8), and it gives the valid ranges (section 2 and 6).

- **Over-range sentinel.** After error 201 `FETC?` returns `+9.90E+37`. `dbm_to_watts(9.9e37)`
  raises `OverflowError` from `10 ** (...)`. The function should reject this explicitly with a clear
  `ValueError` rather than rely on an incidental overflow.
- **Empty list.** `mean_power_dbm([])` raises `ZeroDivisionError`. Raise `ValueError` with a message
  instead, or document the precondition.
- **Stale reading.** After `*RST` the buffer holds -100.00 dBm, and after a setting change `FETC?`
  returns the previous measurement (sections 2 and 3). A stale value is a finite, in-range-looking
  number, so the helper cannot detect it. Averaging it with real readings silently biases the mean
  low; with N readings the one stale value contributes almost no power but still counts in N (for
  N = 2, about -3 dB). This is a caller precondition: the docstring should say the readings must come
  from completed `INIT` / `FETC?` pairs with `SYST:ERR?` returning `0,"No error"`.
- Optional: reject values outside -60 to +20 dBm (section 6), since a reading outside the selected
  range is not calibrated.

## 4. Minor

- `dbm_to_watts` docstring says "for the power log", but it is a general conversion. Say what it is
  and its units (W in, dBm out, or W from dBm), so callers do not confuse it with the log format.
- `list[float]` needs Python 3.9 or later at runtime. Check this matches the project's supported
  version, or use `from __future__ import annotations` / `typing.List`.

## What the author should do

1. Change the divisor from 20 to 10 in `dbm_to_watts`.
2. Add the tests in section 2; they should fail on the current diff and pass after the fix.
3. Add the input checks in section 3 and document the precondition on stale readings.
4. Re-submit for review.

I would not approve this version. The conversion error makes both helpers return wrong power values
for any non-zero reading, and the power log would record these values silently.
