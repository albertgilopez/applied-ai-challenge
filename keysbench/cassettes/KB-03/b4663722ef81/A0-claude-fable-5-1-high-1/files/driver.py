"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


_OPC_POLL_LIMIT = 1000  # *OPC? normally blocks until done; this only guards against a stuck loop
_ERROR_QUEUE_LIMIT = 10  # the KX-100 queue holds 10 entries (MANUAL.md section 8)
_OVER_RANGE_DBM = 9.9e37  # FETC? value on over-range (MANUAL.md section 2, "Ranges")


def _drain_errors(session) -> list[tuple[int, str]]:
    """Read SYST:ERR? until it returns 0,"No error"; return every (code, text) that was queued."""
    errors: list[tuple[int, str]] = []
    for _ in range(_ERROR_QUEUE_LIMIT + 1):
        response = session.query("SYST:ERR?")
        code_text, _, text = response.partition(",")
        try:
            code = int(code_text.strip())
        except ValueError as e:
            raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from e
        if code == 0:
            return errors
        errors.append((code, text.strip().strip('"')))
    # The queue is read oldest first and holds at most 10 entries: more than that means the
    # meter keeps answering with errors, so stop rather than loop forever.
    return errors


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.

    Follows the required measurement sequence of MANUAL.md section 3:
    *CLS, SENS:FREQ, SENS:AVER:COUN, CONF:POW:RANG AUTO, INIT, *OPC?, FETC?, SYST:ERR?.
    FETC? alone never measures (it returns the last completed INIT, or -100.00 dBm after reset),
    so INIT and the *OPC? wait are mandatory before every reading.
    """
    # 1. Start from an empty error queue so the check at the end reflects only this measurement.
    session.write("*CLS")

    # 2. Signal frequency (plain number in Hz). Selects the calibration factor; if it is wrong or
    #    out of band the meter refuses it with -222 and the old frequency stays in force, which the
    #    error check below will catch.
    session.write(f"SENS:FREQ {float(freq_hz):.15g}")

    # 3. Averaging count, sent as given so that a non-integer is refused by the meter (-104).
    session.write(f"SENS:AVER:COUN {averages}")

    # 4. Auto-ranging: LOW below -20 dBm, HIGH otherwise.
    session.write("CONF:POW:RANG AUTO")

    # 5. Trigger one measurement with the settings above.
    session.write("INIT")

    # 6. Wait for the measurement to complete.
    for _ in range(_OPC_POLL_LIMIT):
        if session.query("*OPC?").strip() == "1":
            break
    else:
        raise InstrumentError("*OPC? never returned 1: measurement did not complete")

    # 7. Read the result of that INIT.
    reading = session.query("FETC?").strip()

    # 8. Any queued error means a setting was refused or the reading is invalid: do not use it.
    errors = _drain_errors(session)
    if errors:
        details = "; ".join(f'{code},"{text}"' for code, text in errors)
        raise InstrumentError(f"meter reported error(s): {details}")

    try:
        power_dbm = float(reading)
    except ValueError as e:
        raise InstrumentError(f"unparseable FETC? response: {reading!r}") from e
    if power_dbm >= _OVER_RANGE_DBM:
        # Over-range is normally accompanied by error 201; guard the value itself as well.
        raise InstrumentError(f"measurement over range: FETC? returned {reading}")
    return power_dbm
