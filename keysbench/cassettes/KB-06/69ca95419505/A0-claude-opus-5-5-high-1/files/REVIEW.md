# Review

**Verdict: Request changes. I would not approve this as it stands.**

## Blocking: `dbm_to_watts` uses the wrong exponent (`power.py`, line 13)

```python
return 10 ** (dbm / 20) / 1000
```

dBm measures **power**, so the conversion uses a factor of 10, not 20. A factor of 20 is only for
amplitude quantities such as voltage. The meter's manual says the same thing
(MANUAL.md §7, "Conversions"):

> dBm to watts: P_W = 10^(P_dBm / 10) / 1000

The result is wrong for every reading except exactly 0 dBm:

| Reading | Correct (`/10`) | This PR (`/20`) |
|---|---|---|
| +20 dBm | 0.1 W | 0.01 W (10× too low) |
| -30 dBm | 1 µW | 31.6 µW (31.6× too high) |
| -60 dBm | 1 nW | 1 µW (1000× too high) |

**Fix:** `return 10 ** (dbm / 10) / 1000`.

## Blocking: `mean_power_dbm` is wrong because of the bug above (line 16–19)

`mean_power_dbm` goes back to dBm with `10 * log10(1000 * P)`, which is the correct inverse of the
`/10` formula. Because it gets its watts from the broken `dbm_to_watts`, it actually computes
`10·log10(mean(10^(d/20)))`. That is neither a power mean nor anything else meaningful. Even
for a single reading the result is wrong: `mean_power_dbm([20.0])` returns `10.0`, and
`mean_power_dbm([-40.0])` returns `-20.0`. It halves every value. The function's structure (convert
to linear, average, convert back) is right. Fixing `dbm_to_watts` fixes it.

The test suite didn't catch this because there are no tests. Please add some (see below).

## Should fix (non-blocking, but please address in this PR)

1. **Empty input.** `mean_power_dbm([])` raises `ZeroDivisionError` with no useful message.
   Raise a `ValueError("no readings")`, or document what an empty list should do.
2. **Over-range sentinel.** On an over-range, `FETC?` returns `+9.90E+37` and queues error 201
   (MANUAL.md §2, "Ranges"). Passing that to `dbm_to_watts` raises `OverflowError`
   (`10 ** 9.9e36`), and the log crashes. Either reject non-physical values with a clear error
   (anything above the meter's +20 dBm limit, §6), or document that callers must drop readings
   whose `SYST:ERR?` check failed (§3 step 8). The same applies to the -100.00 dBm reset reading
   (§2), which is not a real measurement. It won't crash, but it will skew a mean.
3. **Tests.** Add at least:
   - `dbm_to_watts(0) == 1e-3`, `dbm_to_watts(30) == 1.0`, `dbm_to_watts(-30) == 1e-6`
     (use `math.isclose`);
   - a round trip: `mean_power_dbm([x]) ≈ x` for several values of x (this catches the /20 bug
     at once);
   - a linear-domain mean: `mean_power_dbm([0, 10])` ≈ `10·log10(5.5)` ≈ 7.40 dBm, not 5 dBm;
   - an empty list raises.

## Minor

- The docstring of `dbm_to_watts` could state the formula and point to MANUAL.md §7, so the
  constant is easy to check.
- `readings_dbm: list[float]` could be `Sequence[float]` / `Iterable[float]`. That's optional.

## Summary

The approach is right: averaging in the linear domain is the correct way to average power
readings. But the core conversion has the wrong constant (`/20` instead of `/10`), so both new
functions return wrong values for almost every input. Please fix the exponent and add tests that
would have caught it. Ideally, also handle empty input and the over-range sentinel. I'll approve
once those changes are in.

