# Write the measurement function of the KX-100 driver

`driver.py` is the start of a driver for the Brevalt KX-100 RF power meter. Implement
`measure_power(session, freq_hz, averages)` from the programming manual, `MANUAL.md`:

- configure the meter for a signal at `freq_hz` and an averaging count of `averages`;
- take one measurement and return it in dBm, as a `float`;
- raise `InstrumentError` (already defined in `driver.py`) if the meter reports any error.

`session` has `write(cmd)`, `read()` and `query(cmd)`. A simulator of the meter, `kx100.py`, is in the
directory: `kx100.KX100(seed)` has the same three methods, if you want to try your function against it.

You may change `driver.py`. Changes to other files are not kept.
