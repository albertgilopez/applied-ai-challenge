# Uncertainty budget for a KX-100 power reading

`uncertainty.py` has one function to write: `combined_uncertainty_pct(reading_dbm, freq_hz, averages,
power_range, gamma_source)`. It returns the combined standard uncertainty u_c of one reading of the
Brevalt KX-100 power meter, in % of reading, as a `float`.

Use a first-order GUM budget built from the meter's specifications in `MANUAL.md` (section 5 for the
contributions, section 7 for the conversions):

- `reading_dbm` is the reading, `freq_hz` the signal frequency, `averages` the averaging count;
- `power_range` is `"LOW"` or `"HIGH"`;
- `gamma_source` is the reflection coefficient magnitude of the source under test.

You may change `uncertainty.py`. Changes to other files are not kept.
