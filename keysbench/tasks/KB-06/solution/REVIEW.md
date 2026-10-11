# Review

Request changes.

The conversion in `dbm_to_watts` is wrong: `return 10 ** (dbm / 20) / 1000` divides by 20, which is the rule for voltage, but dBm is a power ratio and converts as `10 ** (dbm / 10) / 1000` (MANUAL.md section 7).

Every value in the power log is wrong except at 0 dBm, and `mean_power_dbm` inherits the error because it converts back with `10 * log10`.

Fix the divisor to 10 and add a test at a known point, for example 10 dBm is 0.01 W.
