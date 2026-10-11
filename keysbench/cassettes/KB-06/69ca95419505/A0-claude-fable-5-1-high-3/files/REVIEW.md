# Review of `change.diff` (power.py: `dbm_to_watts`, `mean_power_dbm`)

**Verdict: request changes. Do not merge as is.**

The change adds two helpers; the first has a wrong formula, and the second is built on it, so
both return wrong numbers for essentially every input. The fix is a one-character change, but it
needs to be made and covered by a test before this goes in.

## 1. `dbm_to_watts` divides by 20 instead of 10 — blocking

`power.py`, line 13:

```python
return 10 ** (dbm / 20) / 1000
```

dBm is a power ratio, so it is 10 dB per decade, not 20. The `/ 20` form is the one for
amplitude quantities (volts, reflection coefficients), not power. The manual states the correct
conversion explicitly (MANUAL.md §7, "Conversions"):

> dBm to watts: P_W = 10^(P_dBm / 10) / 1000

The function should be:

```python
return 10 ** (dbm / 10) / 1000
```

How wrong the current version is, across the meter's own -60 to +20 dBm range (§6):

| Input | Current result | Correct result | Error |
|---|---|---|---|
| 0 dBm | 1.000 mW | 1.000 mW | none (the only point where it agrees) |
| +10 dBm | 3.16 mW | 10.0 mW | 3.2× low |
| +20 dBm | 10.0 mW | 100 mW | 10× low |
| -23.47 dBm (the `FETC?` example in §2) | 67.1 µW | 4.50 µW | 15× high |
| -60 dBm | 1.00 µW | 1.00 nW | 1000× high |

The error grows with distance from 0 dBm, so the readings the log is most likely to contain
(tens of dB below 0) are the ones that come out most wrong. Note that a spot check at 0 dBm
would pass — please don't let that be the only test (see §3 below).

## 2. `mean_power_dbm` inherits the bug and is internally inconsistent — blocking

`power.py`, lines 18–19:

```python
watts = [dbm_to_watts(r) for r in readings_dbm]
return 10 * math.log10(1000 * sum(watts) / len(watts))
```

The approach is right: averaging power readings should be done in the linear (watt) domain and
converted back, and the watts-to-dBm step on line 19 matches §7 (`P_dBm = 10·log10(1000·P_W)`).
But line 18 goes to watts with the wrong exponent and line 19 comes back with the right one, so
the round trip is not the identity. In effect the function returns `10·log10(mean(10^(r/20)))`,
which for N identical readings is **half** the reading:

- `mean_power_dbm([-20.0])` → `-10.00`, should be `-20.00`
- `mean_power_dbm([-20.0, -20.0])` → `-10.00`, should be `-20.00`
- `mean_power_dbm([-10.0, -20.0])` → `-7.16`, should be `-12.60`

A "mean" that doesn't return the value when all inputs are equal is clearly wrong. Fixing
`dbm_to_watts` fixes this function with no further change needed, but it should get its own
tests so that the two functions are checked to agree with each other, not just with the manual.

## 3. Missing tests — required before merge

The diff adds no tests, and the bug above would have been caught by the most basic one. Please
add at least:

- `dbm_to_watts(0.0) == 1e-3`, `dbm_to_watts(10.0) ≈ 1e-2`, `dbm_to_watts(-30.0) ≈ 1e-6`,
  `dbm_to_watts(20.0) ≈ 0.1`. Include points other than 0 dBm — that is the one input where
  `/10` and `/20` coincide.
- `mean_power_dbm([x]) ≈ x` and `mean_power_dbm([x, x]) ≈ x` for some non-zero `x` (round trip).
- `mean_power_dbm([-10.0, -20.0]) ≈ -12.60` (mean of 0.1 mW and 0.01 mW is 0.055 mW).

## 4. Minor / non-blocking

- `mean_power_dbm([])` raises `ZeroDivisionError` from `len(watts)`. Either document that the
  list must be non-empty or raise a `ValueError` with a clear message. Not a blocker, but cheap.
- The manual says the reset reading `-100.00 dBm` (§2, `*RST` / `FETC?`) and the over-range
  sentinel `+9.90E+37` (§2, "Ranges") are not real measurements. Feeding either into
  `mean_power_dbm` silently produces garbage (the sentinel alone will dominate any average). This
  is really the caller's responsibility per §3 step 8 ("do not use the reading"), so I'm not
  asking for a change here, but a one-line note in the docstring that readings must be validated
  first would help the next person.
- The docstring for `mean_power_dbm` is good — it says *why* it goes through watts. Keep that.

## Summary for the author

1. Change `dbm / 20` to `dbm / 10` on line 13 of `power.py` (per MANUAL.md §7).
2. Add the tests in §3 above; make sure they include non-zero dBm values.
3. Optionally guard the empty-list case in `mean_power_dbm`.

Once (1) and (2) are in, I'd expect to approve on the next pass.
