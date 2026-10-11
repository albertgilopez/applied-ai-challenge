# Review of change to power.py

**Verdict: do not approve (request changes).** The conversion is wrong, and it makes both new helpers return wrong numbers.

## Blocking: `dbm_to_watts` uses the wrong exponent (power.py, line 13 after the change)

```python
return 10 ** (dbm / 20) / 1000
```

MANUAL.md section 7 gives dBm to watts as `P_W = 10^(P_dBm / 10) / 1000`. The divisor is 10, not 20. Dividing by 20 is the formula for a voltage or amplitude ratio. It is not the formula for power. The function returns the square root of the correct linear value (before the 1/1000 scaling).

Examples:
- 0 dBm should be 0.001 W. The code gives 0.001 W, which is correct only because 10^0 = 1.
- +20 dBm should be 0.1 W. The code gives 10^1 / 1000 = 0.01 W, which is 10x too small.
- -30 dBm should be 1 µW. The code gives 10^-1.5 / 1000 ≈ 31.6 µW, which is 31.6x too large.

Any non-zero reading is wrong, and the error grows with distance from 0 dBm.

## Blocking: `mean_power_dbm` is wrong as a result

The watts-to-dBm step on line 19 is correct (`10·log10(1000·P_W)`), but it takes the output of the broken `dbm_to_watts`. The errors do not cancel. For N identical readings the function returns half the input in dB. For example, -20 dBm gives -10 dBm, and +10 dBm gives +5 dBm. For mixed readings the result is also not the correct linear mean. Fixing the exponent in `dbm_to_watts` fixes this function as well.

## Should fix

1. **Empty input.** `mean_power_dbm([])` raises `ZeroDivisionError`. Either raise a clear `ValueError` or document the precondition.
2. **Invalid readings are not handled.** According to the manual, `FETC?` returns `+9.90E+37` on over-range (error 201). It returns `-100.00` after `*RST`, before any `INIT`. These are not measurements. Averaged in, `+9.90E+37` dBm overflows (`OverflowError` in `10 ** ...`). A `-100.00` placeholder silently biases the mean. The docstring should say that callers must drop readings whose `SYST:ERR?` was not `0,"No error"` (manual section 3, step 8). Alternatively, the function could reject the sentinel values.
3. **No tests.** This bug would have been caught by a single round-trip test. Please add tests:
   - `dbm_to_watts(0) == 1e-3`, `dbm_to_watts(30) == 1.0`, `dbm_to_watts(-30) == 1e-9`.
   - `mean_power_dbm([x, x, x]) ≈ x`.
   - Two readings 3 dB apart: `mean_power_dbm([0, 3])` is about +1.76 dBm, not 1.5.
4. **Minor.** The result of `mean_power_dbm` has more digits than the instrument's 0.01 dB resolution (manual section 6). If it is printed, pass it through `format_reading`, and do not present more precision than the meter provides.
5. **Minor.** `list[float]` in the annotation needs Python 3.9 or later. Check that this matches the project's minimum version.

## Suggested fix

```python
return 10 ** (dbm / 10) / 1000
```

After this change, re-check `mean_power_dbm` against the tests above. Resubmit and I will review again.
