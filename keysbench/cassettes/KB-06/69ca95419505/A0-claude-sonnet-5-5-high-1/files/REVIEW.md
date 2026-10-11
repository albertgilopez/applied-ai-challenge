# Review of the change to `power.py`

**Verdict: do not approve (request changes).** There is one definite bug, and it affects both new functions. There are also some robustness gaps.

## 1. Blocker: `dbm_to_watts` uses the wrong divisor (`power.py` line 13)

```python
return 10 ** (dbm / 20) / 1000      # wrong
```

Power in dBm is a power ratio, so the exponent is `dbm / 10`. MANUAL.md section 7 gives
`P_W = 10^(P_dBm / 10) / 1000`. A divisor of 20 is the formula for voltage or amplitude ratios. The code
therefore returns the square root of the linear ratio, so the result is wrong in dB terms by a factor of 2.

Examples:

| Input | Expected | Actual |
|---|---|---|
| 0 dBm | 1e-3 W | 1e-3 W (correct only by coincidence, because the exponent is 0) |
| +30 dBm | 1.0 W | 0.0316 W |
| -20 dBm | 1e-5 W | 1e-4 W |
| -100 dBm (reset reading) | 1e-13 W | 1e-8 W |

A test at 0 dBm would pass, so 0 dBm is a poor check value.

The bug carries into `mean_power_dbm`. It converts back with the correct `10*log10(1000*P)`, so the
two errors don't cancel. The result is the true value scaled by 1/2 in dB. For example, the mean of
`[-20, -20]` comes out as -10 dBm, and `[-40]` comes out as -20 dBm. This is silent and large, and nothing
flags it. The function would produce plausible but wrong values in the power log.

**Fix:** use `10 ** (dbm / 10) / 1000`.

## 2. Robustness issues in `mean_power_dbm` (should fix, or document)

- **Empty list:** `len(watts) == 0` raises a bare `ZeroDivisionError`. Raise a clear `ValueError`, or
  state the behaviour in the docstring.
- **Invalid instrument values:** MANUAL.md says `FETC?` returns `+9.90E+37` on over-range, with error 201 queued.
  Passing that into `dbm_to_watts` raises `OverflowError` (`10 ** 4.95e36`). The reset reading of -100.00 dBm
  that `FETC?` returns before any `INIT` is valid as a number but is not a measurement. It would be
  averaged in silently. The manual (section 3, step 8) says a reading must not be used when
  `SYST:ERR?` reports an error. The helper should either reject or filter such values, or the docstring
  should say callers must do so first.
- **Resolution:** the instrument resolves 0.01 dB (manual section 6), and `format_reading` prints 2 decimals.
  The mean is returned unrounded. This is fine if it is only formatted for display, but the result should not be
  presented as more precise than the instrument.

## 3. Tests and minor points

- No tests were added. A test with at least one non-zero value such as +30 dBm -> 1 W, -30 dBm -> 1e-6 W,
  and a round trip would have caught the bug. Add a `mean_power_dbm` test with `[0, 0]` -> 0 and `[-20, -20]` -> -20.
  Also add a test where the arithmetic and the linear mean differ, such as `[0, -10]` -> about -2.6 dBm.
- Docstring of `dbm_to_watts` says "for the power log", which does not say what it does. It is fine
  once the formula is right.
- `list[float]` needs Python 3.9 or later. Check this matches the project's supported version.

## Summary for the author

Change `/ 20` to `/ 10` in `dbm_to_watts`, add tests with non-zero dBm values, and handle the empty-list
and invalid-reading cases in `mean_power_dbm`. I would re-review after that.

