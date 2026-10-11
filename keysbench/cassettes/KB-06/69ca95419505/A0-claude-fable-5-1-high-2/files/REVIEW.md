# Review: add `dbm_to_watts` and `mean_power_dbm` to `power.py`

**Verdict: Request changes. Do not merge.**

## 1. Blocking: `dbm_to_watts` uses the wrong conversion (`power.py`, line 13)

```python
return 10 ** (dbm / 20) / 1000
```

dBm is a *power* ratio, so the exponent must be `dbm / 10`. Dividing by 20 is the
voltage/amplitude form (20·log10 of a voltage ratio) and does not apply here. The manual is
explicit, §7 "Conversions":

> dBm to watts: P_W = 10^(P_dBm / 10) / 1000

Consequences across the KX-100's own power range (-60 dBm to +20 dBm, manual §6):

| Input (dBm) | Code returns | Correct value | Error |
|---|---|---|---|
| 0.00 | 1.00 mW | 1.00 mW | none (only point where both agree) |
| +10.00 | 3.16 mW | 10.0 mW | 3.2× low |
| +20.00 | 10.0 mW | 100 mW | 10× low |
| -23.47 (manual's `FETC?` example) | 67.1 µW | 4.50 µW | 15× high |
| -60.00 | 1.00 µW | 1.00 nW | 1000× high |

The function is only right at exactly 0 dBm, which is why a casual spot-check would not catch it.
Anything in the power log built on it (and any uncertainty budget that converts the nW zero-offset
terms to "% of reading" per manual §5/§7, which needs the reading in watts) will be wrong.

**Fix:**

```python
def dbm_to_watts(dbm: float) -> float:
    """Convert a reading in dBm to watts, for the power log."""
    return 10 ** (dbm / 10) / 1000
```

## 2. Blocking by dependency: `mean_power_dbm` returns wrong results (`power.py`, lines 16-19)

The watts→dBm step on line 19 uses the correct form from the manual
(`P_dBm = 10·log10(1000·P_W)`), but because it feeds on the broken `dbm_to_watts`, the
round trip is not even self-consistent. Effectively every input is halved in dB:

- `mean_power_dbm([10.0, 10.0])` → **5.00 dBm** (should be 10.00; the mean of identical readings
  must be that reading).
- `mean_power_dbm([-23.47])` → **-11.74 dBm** (should be -23.47).
- `mean_power_dbm([-20.0, -10.0])` → **-6.19 dBm** (correct: -12.39 dBm).

Averaging in the linear domain is the right approach and the function needs no change of its own;
it is correct as soon as item 1 is fixed. But please do not merge it on top of the current
`dbm_to_watts`.

## 3. Should fix before merge: no tests

Neither helper has a test, and the bug above would have been caught by the most basic one.
Please add at least:

```python
assert dbm_to_watts(0.0) == pytest.approx(1e-3)
assert dbm_to_watts(10.0) == pytest.approx(1e-2)       # catches /20 vs /10
assert dbm_to_watts(-30.0) == pytest.approx(1e-6)
assert mean_power_dbm([10.0, 10.0]) == pytest.approx(10.0)
assert mean_power_dbm([-23.47]) == pytest.approx(-23.47)
assert mean_power_dbm([-20.0, -10.0]) == pytest.approx(-12.39, abs=0.01)
```

The second and fourth assertions fail on the current diff.

## 4. Non-blocking: robustness of `mean_power_dbm` against the meter's sentinel values

Not required for this PR, but worth a follow-up or a docstring note, since these helpers are
meant for the KX-100 log specifically:

- **Empty list** raises `ZeroDivisionError` on `len(watts)`. Either raise a clear `ValueError`
  or document that the caller must not pass an empty list.
- **Over-range sentinel.** On LOW range over-range `FETC?` returns `+9.90E+37` (manual §2,
  "Ranges"). `10 ** (9.9e37 / 10)` raises `OverflowError`, and if it didn't it would swamp the
  mean. The manual (§3 step 8) says such readings must not be used; the caller should filter them
  on the error queue, but the helper could reject values outside -60..+20 dBm defensively.
- **Reset reading.** After `*RST`/power-on, `FETC?` returns -100.00 dBm (manual §2) without an
  error. If one of these slips into a batch it will not blow up but will silently bias the mean
  (in the linear domain it is ~0 W, so it just dilutes the average by 1/N). Same remedy: range-check
  or document.

## Summary for the author

1. Change `dbm / 20` to `dbm / 10` in `dbm_to_watts` (manual §7).
2. Add the tests above; confirm `mean_power_dbm([x, x]) == x`.
3. Optionally add input validation / documentation for empty input and the meter's `+9.90E+37`
   and `-100.00` sentinel values.

With (1) and (2) done I would approve.
