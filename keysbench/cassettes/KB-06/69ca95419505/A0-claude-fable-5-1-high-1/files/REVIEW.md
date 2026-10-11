# Review

**Verdict: Request changes. Do not merge.**

The change adds `dbm_to_watts` and `mean_power_dbm`. The first one is wrong, and the second one
is built on it, so both return incorrect values for essentially every input. Details below.

## 1. `dbm_to_watts` uses the wrong exponent (blocking)

`power.py`, line 13:

```python
return 10 ** (dbm / 20) / 1000
```

dBm is a *power* ratio, so the conversion is `10^(dBm/10)`, not `10^(dBm/20)`. The `/20` form is
the voltage/amplitude-ratio formula and does not apply here. The manual states the correct formula
explicitly (MANUAL.md §7, "Conversions"):

> dBm to watts: P_W = 10^(P_dBm / 10) / 1000

Concretely, with the code as written:

| Input (dBm) | Code returns | Correct value | Error |
|---|---|---|---|
| 0.00 | 1.00 mW | 1.00 mW | none (the only point where they agree) |
| +10.00 | 3.16 mW | 10.0 mW | 3.2× too small |
| +20.00 | 10.0 mW | 100 mW | 10× too small |
| -23.47 (the manual's example `FETC?` value) | 67.1 µW | 4.50 µW | 15× too large |
| -60.00 | 1.00 µW | 1.00 nW | 1000× too large |

The error is zero at 0 dBm and grows with distance from it, so a quick spot check at 0 dBm would
not catch it. Over the instrument's full range (-60 to +20 dBm, §6) the result is off by up to
three orders of magnitude.

**Fix:** change `dbm / 20` to `dbm / 10`:

```python
def dbm_to_watts(dbm: float) -> float:
    """Convert a reading in dBm to watts, for the power log."""
    return 10 ** (dbm / 10) / 1000
```

## 2. `mean_power_dbm` inherits the bug (blocking, fixed by #1)

`power.py`, lines 18–19. The approach is right: average in watts, convert back with
`10·log10(1000·P_W)`, which matches the manual's watts→dBm formula. But because it goes through the
broken `dbm_to_watts`, the forward and reverse conversions don't invert each other and the result
is wrong even for trivial inputs:

- `mean_power_dbm([-20.0])` returns **-10.0**, not -20.0. For a single reading the function
  returns half the input, because `10·log10(10^(x/20)) = x/2`.
- `mean_power_dbm([-10.0, -30.0])` returns **-7.60**, correct answer is -12.97.

No separate code change is needed in this function once #1 is fixed, but it must be re-tested.

## 3. Tests (required before approval)

There are no tests in the diff. Either of the cases above would have failed immediately. Please add
at least:

- `dbm_to_watts(0.0) == 1e-3`, `dbm_to_watts(10.0) ≈ 1e-2`, `dbm_to_watts(-30.0) ≈ 1e-6`.
- Round-trip: `mean_power_dbm([x]) ≈ x` for a few x across -60…+20.
- A two-point case with a hand-computed answer, e.g. `mean_power_dbm([-10.0, -30.0]) ≈ -12.97`.

## 4. Non-blocking comments

These don't need to hold up the fix for #1, but the author should consider them:

- **Empty input.** `mean_power_dbm([])` raises `ZeroDivisionError` from `len(watts)`. Either
  document that an empty list is not allowed or raise a `ValueError` with a clear message.
- **Sentinel readings.** Per the manual, `FETC?` returns `+9.90E+37` on over-range (§2, Ranges) and
  `-100.00` after `*RST` (§2, `*RST`). Both are outside the measurable range (-60 to +20 dBm, §6)
  and neither is a real power. If either ever reaches `mean_power_dbm`, it will silently dominate
  (over-range) or be swallowed (reset value) in the average. The caller is supposed to check
  `SYST:ERR?` before using a reading (§3 step 8), but a guard here, or at least a docstring note
  that inputs must be validated readings, would be cheap insurance.
- `list[float]` in the annotation needs Python 3.9+. Fine if that's the project's floor; just
  flagging it since the rest of the file didn't previously depend on it.

## Summary

The core conversion formula is wrong (`/20` instead of `/10`), contradicting MANUAL.md §7, and
every value produced by both new helpers is incorrect except at exactly 0 dBm. Fix the exponent,
add the tests listed above, and I'll take another look. **Not approved as-is.**
