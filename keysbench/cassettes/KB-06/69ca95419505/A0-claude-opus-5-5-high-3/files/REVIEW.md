# Review: `dbm_to_watts` / `mean_power_dbm` for the KX-100 power log

**Verdict: Request changes. Do not merge as it is.** The dBm-to-watts conversion uses the wrong
formula, so every value either helper produces is wrong except at exactly 0 dBm.

## 1. Blocking: `dbm_to_watts` divides by 20 instead of 10 (power.py, line 13)

```python
return 10 ** (dbm / 20) / 1000
```

dBm is a **power** ratio (relative to 1 mW), so the exponent is `dbm / 10`. The `/20` form is for
amplitude quantities such as voltage, and it does not apply here. MANUAL.md §7 gives the formula
directly:

> dBm to watts: P_W = 10^(P_dBm / 10) / 1000

Effect, worked out by hand:

| Reading | Correct (W) | This PR (W) | Error |
|---|---|---|---|
| +20 dBm | 1.0e-1 | 1.0e-2 | 10× too low |
| 0 dBm | 1.0e-3 | 1.0e-3 | none |
| -30 dBm | 1.0e-6 | 3.16e-5 | 31.6× too high |
| -60 dBm | 1.0e-9 | 1.0e-6 | 1000× too high |

The two formulas only agree at 0 dBm. That's the value a quick spot check would most likely use,
which is probably how this got past testing. In dB terms the result is off by half the reading,
which across the meter's -60 to +20 dBm range (§6) is an error of up to 30 dB.

**Fix:** `return 10 ** (dbm / 10) / 1000`

## 2. Blocking (follows from 1): `mean_power_dbm` returns wrong values

`mean_power_dbm` converts readings to watts with the broken `dbm_to_watts`, then converts back with
`10 * math.log10(1000 * P)`, which is the correct inverse from §7. Because the forward and reverse
conversions don't match, even a single reading doesn't round-trip:

- `mean_power_dbm([-20.0])` returns **-10.00 dBm** (it should be -20.00).
- `mean_power_dbm([-20.0, -10.0])` returns about **-6.82 dBm**. The correct linear-domain mean is
  10·log10(1000 · (1e-5 + 1e-4) / 2) ≈ **-12.60 dBm**.

Averaging in the linear (watts) domain and converting back is the right approach, and the function
will be correct once item 1 is fixed. Nothing else needs to change in it for the normal case.

## 3. Should fix: invalid inputs

- **Over-range readings.** On over-range, `FETC?` returns `+9.90E+37` (§2, Ranges) and queues
  error 201. Passing that to `dbm_to_watts` (and so to `mean_power_dbm`) raises `OverflowError`
  from `10 ** 9.9e36`, a confusing failure deep in the logger. Either reject values above the
  instrument's limit (+20 dBm, §6) or the 9.9e37 sentinel explicitly with a clear `ValueError`, or
  document that callers must filter readings that failed the `SYST:ERR?` check (§3 step 8: "do not
  use the reading").
- **Reset reading.** After power-on or `*RST`, `FETC?` returns -100.00 dBm (§2), which is below
  the -60 dBm floor. If it ends up in a list it pulls the mean down without any warning. Consider
  rejecting or flagging readings outside -60 to +20 dBm, or at least say in the docstring that inputs
  must be valid measurements.
- **Empty list.** `mean_power_dbm([])` raises `ZeroDivisionError`. Raise a `ValueError` with a clear
  message instead, or document that the list must not be empty.

## 4. Tests

The PR adds no tests. Please add tests that would have caught item 1, using values other than
0 dBm:

- `dbm_to_watts(0) == 1e-3`, `dbm_to_watts(20) == 0.1`, `dbm_to_watts(-30) == 1e-6`
  (use `math.isclose`)
- round trip: `mean_power_dbm([x]) ≈ x` for several values of x across -60 to +20
- `mean_power_dbm([-20, -10]) ≈ -12.60`
- whatever behaviour you choose in item 3 for empty, over-range and out-of-range input

## Minor

- The `dbm_to_watts` docstring could give the formula and cite MANUAL.md §7.
- `mean_power_dbm` could reuse a `watts_to_dbm` helper, so the inverse conversion lives in one
  place next to the forward one.

## Summary

| # | Location | Severity | Action |
|---|---|---|---|
| 1 | `dbm_to_watts`, line 13 | Blocking | Use `dbm / 10` (MANUAL §7) |
| 2 | `mean_power_dbm` | Blocking (fixed by 1) | Re-check after the fix; add a round-trip test |
| 3 | both helpers | Should fix | Handle or document over-range (9.9e37), reset (-100 dBm) and empty input |
| 4 | tests | Should fix | Add tests at values other than 0 dBm |

I'll approve once items 1 and 4 are addressed and item 3 is handled or documented.
