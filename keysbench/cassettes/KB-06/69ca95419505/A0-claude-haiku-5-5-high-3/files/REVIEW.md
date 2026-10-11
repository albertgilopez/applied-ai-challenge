# Review of change.diff (power.py: `dbm_to_watts`, `mean_power_dbm`)

## Verdict

**Do not approve.** `dbm_to_watts` uses the wrong exponent, so both new helpers return wrong numbers
for every input except 0 dBm. The change also has no tests and no input validation against the
instrument's documented limits.

## 1. Blocking: wrong exponent in `dbm_to_watts` (power.py, line 16)

```python
return 10 ** (dbm / 20) / 1000
```

The manual (section 7) gives `P_W = 10^(P_dBm / 10) / 1000`. The code divides by 20, which is the
voltage (amplitude) convention, not the power convention. The result is off by a factor
`10^(-dBm/20)`:

| dBm in | Correct W | Code returns W |
|---|---|---|
| -30 | 1.00e-6 | 3.16e-5 (×31.6) |
| -20 | 1.00e-5 | 1.00e-4 (×10) |
| 0 | 1.00e-3 | 1.00e-3 (correct only here) |
| +10 | 1.00e-2 | 3.16e-3 (×0.316) |

Fix: `return 10 ** (dbm / 10) / 1000`.

## 2. Blocking: `mean_power_dbm` returns wrong results because of (1)

Line 22 (`10 * math.log10(1000 * sum(watts) / len(watts))`) is the right watts-to-dBm conversion
(section 7), and the linear-domain averaging in the docstring is the right method for power. The
result is still wrong because it consumes the bad watts. With the current code, a single reading
`r` comes back as `r / 2`:

- `mean_power_dbm([-20.0])` returns `-10.0`, not `-20.0`.
- `mean_power_dbm([-30.0])` returns `-15.0`, not `-30.0`.
- `mean_power_dbm([0.0, 10.0])` returns about `3.18`, not `7.40`.
  (The correct linear mean of 1 mW and 10 mW is 5.5 mW = 7.40 dBm.)

Any test that checks a single reading against itself would have caught this. Please add tests (see
section 5).

## 3. Missing validation of inputs (both functions)

The manual sets limits the helpers should enforce or at least document:

- **Over-range sentinel.** Section 2 says that on LOW, an input above -10 dBm makes `FETC?` return
  `+9.90E+37` and queue error 201. With the current code, passing that value raises
  `OverflowError` inside `dbm_to_watts`. The sentinel must never reach the averaging. The caller
  should check `SYST:ERR?` (section 3, step 8), and the helper should reject values outside the
  instrument's power range.
- **Reset reading.** After `*RST` or power-on, `FETC?` returns `-100.00` dBm (section 2). This is
  outside the -60 to +20 dBm power range (section 6). It is not a measurement. It currently passes
  silently into the mean.
- **Power range.** Section 6 gives -60 to +20 dBm. Readings outside that range should be rejected,
  not averaged.
- **NaN / inf.** Non-finite values are not rejected.
- **Empty list.** `mean_power_dbm([])` raises `ZeroDivisionError`. This should be a clear
  `ValueError`, or the docstring should say so.
- **Mixed settings.** Calibration is applied at the frequency set by `SENS:FREQ` (sections 3 and 4),
  and the readings are only valid for the settings they were taken with. A mean across readings
  taken at different frequencies (or before a setting change, section 2 `FETC?` note) is wrong and
  is not detected. The docstring should state that all readings must share one `SENS:FREQ` and
  range setting, or the caller should be responsible for that.

## 4. Resolution (minor, a judgement call)

Section 6: "A reading finer than the resolution is not available from the instrument," and no
averaging count extends the limits. `mean_power_dbm` returns an unrounded float (e.g. `-23.4567`).
This implies more precision than the 0.01 dB instrument resolution. Consider rounding the result to
0.01 dB, or document that the software mean is not a finer-resolution reading. `format_reading`
hides this on output, but the raw value is still returned.

Also, `SENS:AVER:COUN` already averages inside the instrument. Software averaging on top of that is
allowed, but the author should say whether it is intended, so the uncertainty budget (section 5,
noise term 2.0/√N) is not applied twice.

## 5. Tests to add before merge

Check these against the manual's conversion (section 7):

- `dbm_to_watts(0) == 1e-3`, `dbm_to_watts(10) == 1e-2`, `dbm_to_watts(-30) == 1e-6`.
- `mean_power_dbm([x]) == x` for x in {-60, -30, -20, 0, 10, 20}.
- `mean_power_dbm([0, 10])` is about `7.40`.
- `mean_power_dbm([])` raises `ValueError` (after the fix in section 3).
- Out-of-range inputs (`9.9e37`, `-100`, `nan`) are rejected.

## 6. What the author should do

1. Change the exponent in `dbm_to_watts` from `/ 20` to `/ 10`.
2. Add the tests in section 5, and check them before re-requesting review.
3. Add input validation for the instrument's power range, sentinel, reset reading, NaN, and empty
   input.
4. Document that all readings must share one frequency and range setting.
5. Decide whether the mean is rounded to 0.01 dB.

I would approve after items 1 and 2 are done and items 3 to 5 are either done or explicitly
accepted.
