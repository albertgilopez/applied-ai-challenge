# Review: add `dbm_to_watts` and `mean_power_dbm` to `power.py`

**Verdict: Request changes. Do not approve as it stands.**

## Blocking: `dbm_to_watts` uses the wrong exponent (power.py line 13)

```python
return 10 ** (dbm / 20) / 1000
```

dBm is a power ratio, so the divisor is **10**, not 20. Dividing by 20 is the formula for voltage or
field amplitude. The manual (MANUAL.md section 7, Conversions) says:

> dBm to watts: P_W = 10^(P_dBm / 10) / 1000

As written, every value is wrong except 0 dBm:

| Reading | Correct (W) | This PR (W) |
|---|---|---|
| +20 dBm | 0.1 | 0.01 |
| -20 dBm | 1e-5 | 1e-4 |
| -60 dBm | 1e-9 | 1e-6 |

At -60 dBm the result is 1000 times too large.

**Fix:** `return 10 ** (dbm / 10) / 1000`

## Blocking: `mean_power_dbm` is wrong because of the bug above (lines 16-19)

`mean_power_dbm` converts with the broken `dbm_to_watts`, then converts back with the correct
`10·log10(1000·P_W)`. Because the two conversions don't match, the result isn't the reading's power
level at all. It is roughly half the dBm value. Even for a single reading it doesn't return its
input: `mean_power_dbm([-20.0])` returns **-10.0** where it should return -20.0. The averaging is
also done on amplitudes rather than powers, so it isn't the linear-domain power mean the docstring
promises.

Fixing `dbm_to_watts` fixes this function too. After the fix, `mean_power_dbm([d]) == d`, and
`mean_power_dbm([-10, -20])` is about -12.60 dBm (the mean of 100 µW and 10 µW is 55 µW).

## Also needs attention (smaller, but please address in this PR)

1. **Empty input:** `mean_power_dbm([])` raises a bare `ZeroDivisionError`. Raise a clear
   `ValueError` instead, or document that the list must not be empty.
2. **Instrument sentinel values:** on an over-range, `FETC?` returns `+9.90E+37` and queues error
   201 (MANUAL.md section 2, Ranges). Passing that to `dbm_to_watts` raises `OverflowError` (with
   either exponent). After `*RST` or power-on, the meter returns the reset reading -100.00 dBm, which
   is outside the -60 to +20 dBm power range (section 6). That value would be averaged in silently
   and pull the mean down. Section 3 says a reading must not be used if the error queue isn't clean.
   Either reject values outside -60 to +20 dBm here, or state in the docstring that callers must pass
   only validated readings.
3. **No tests.** Add unit tests that would have caught this bug:
   - `dbm_to_watts(0) == 1e-3`
   - `dbm_to_watts(30) == 1.0`
   - `dbm_to_watts(-30) == 1e-6`
   - `mean_power_dbm([x]) == x` for several values of x
   - one mixed-value mean, such as `[-10, -20]` giving about -12.60
   - the empty-list case

## Summary for the author

- Change `/ 20` to `/ 10` in `dbm_to_watts` (required).
- Handle empty input in `mean_power_dbm` (required).
- Decide how to handle over-range (`+9.90E+37`) and reset (`-100.00`) readings, and document it.
- Add the tests listed above.

I'll re-review once these are in.
