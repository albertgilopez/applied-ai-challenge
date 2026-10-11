# Review

Approve, with nits.

Averaging in the linear domain before converting back to dBm is the right approach, nice.

Nit: rename `dbm` to `level_dbm` in `dbm_to_watts` for consistency with the rest of the module.

Nit: `mean_power_dbm` should raise a clear error on an empty list instead of dividing by zero.
