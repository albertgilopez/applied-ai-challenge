# Review

**Verdict: do not approve. Request changes.** The change is a dBm-to-watts conversion with the wrong
formula, so both helpers return wrong values for every input except 0 dBm.

## 1. Blocking: `dbm_to_watts` uses the amplitude formula (power.py, `dbm_to_watts`)

The diff has:

```python
return 10 ** (dbm / 20) / 1000
```

The divisor is 20. The manual (section 7) gives the power conversion as `P_W = 10^(P_dBm / 10) / 1000`,
and the divisor must be 10. `/ 20` gives the voltage-ratio form, which is wrong for power. The error
hides at 0 dBm, where both forms give 0.001 W, so a test at 0 dBm passes. It shows up at any other
level:

- `dbm_to_watts(-20)` returns 1e-4 W. The correct value is 1e-5 W. The result is 10x too large (10 dB).

## 2. Blocking: `mean_power_dbm` returns wrong results because of (1)

`mean_power_dbm` is built correctly (average in linear watts, then `10·log10(1000·P_W)`, which matches
manual section 7). It inherits the error from `dbm_to_watts`, so:

- `mean_power_dbm([-20.0])` returns **-10.0 dBm**. It should return -20.0. For one reading the output
  is always half the input in dB.
- `mean_power_dbm([-20.0, -30.0])` returns **-11.82 dBm**. The correct linear mean is 5.5 µW, which is
  **-22.60 dBm**. The error is about 10.8 dB.

The fix for (1) fixes (2). Nothing else in `mean_power_dbm` needs to change.

## 3. Should fix: no input validation for the sentinel and out-of-range values

`mean_power_dbm` accepts any float. Manual section 2 and section 8 define values that must not be
used as readings:

- **Over-range:** `FETC?` returns `+9.90E+37` when the input exceeds the LOW range, with error 201
  queued. Passing this value in makes `10 ** (dbm / 20)` raise `OverflowError`. That is a crash, not a
  wrong number, but it is still an unhandled error in a logging helper.
- **Reset reading:** `*RST` loads -100.00 dBm, and `FETC?` returns it until the first `INIT`. This value
  is a valid float, so it would be averaged in silently and bias the mean.
- **Out of span:** the instrument covers -60 to +20 dBm (manual section 6). Readings outside this span
  are not calibrated results.

Suggested change: reject values outside -60 to +20 dBm with `ValueError` in `mean_power_dbm` (this also
catches the sentinel and the reset value). Also document that the caller must check `SYST:ERR?` and
discard the reading when it is not `0,"No error"` (manual section 3, step 8). The helper cannot see
the error queue, so the caller has to do that check.

## 4. Should fix: empty list

`mean_power_dbm([])` raises `ZeroDivisionError`. Raise a `ValueError` with a clear message, or
document the precondition.

## 5. Should consider: mixed ranges

Manual section 2 says HIGH below -30 dBm is dominated by its zero offset (±50 nW), and the LOW zero offset
is ±0.5 nW. If the list mixes readings from LOW and HIGH, or includes HIGH readings below -30 dBm, the
mean inherits that bias. The helper has no information about the range. Document that all readings
must come from one range, or that readings must be at or above -30 dBm when taken on HIGH.

## 6. Should consider: precision of the output

The mean is a computed value. It can have more digits than the 0.01 dB instrument resolution (manual
section 6). That is fine as a statistic, but the log should not present it as a `FETC?`-style reading.
`format_reading` rounds to two decimals, so this matters only if the unrounded value is stored or
compared. The docstring should say that the result is derived from readings and is not an instrument
measurement.

## 7. Minor: hunk header and tests

- The hunk header says `@@ -1,6 +1,20 @@`. By my count the new side of the hunk has 19 lines (6 context plus
  13 added), which matches `power.py` as it stands. Regenerate the diff and confirm it applies cleanly
  (`git apply --check`).
- The change adds no tests. Add tests that would have caught (1) and (2):
  - `dbm_to_watts(0) == 0.001`
  - `dbm_to_watts(-20) == pytest.approx(1e-5)`
  - `mean_power_dbm([-20]) == pytest.approx(-20)`
  - `mean_power_dbm([-20, -30]) == pytest.approx(-22.60, abs=0.01)`
  - `mean_power_dbm([])` raises
  - out-of-span inputs (for example `9.9e37`, `-100.0`) raise

## Requested changes

1. In `dbm_to_watts`, change the divisor from `20` to `10`.
2. Add the tests in section 7. The 0 dBm case alone is not enough.
3. Validate inputs in `mean_power_dbm` (section 3) and handle the empty list (section 4).
4. Update the docstrings for the range precondition and for the derived-value meaning (sections 5 and 6).
5. Regenerate the diff so the hunk header is correct.

I would approve after items 1 to 3 are done and the tests pass. Items 4 and 5 can go in the same PR.
