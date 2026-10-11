"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


_NO_ERROR_CODE = 0
_OPC_POLL_LIMIT = 1000  # upper bound on *OPC? polls so a misbehaving meter cannot hang us forever


def _drain_errors(session) -> list[str]:
    """Read SYST:ERR? until the queue reports 0,"No error"; return the entries read, oldest first.

    The queue holds at most 10 entries (MANUAL.md section 8), so this loop is bounded.
    """
    errors: list[str] = []
    while True:
        response = session.query("SYST:ERR?").strip()
        code_text, _, _ = response.partition(",")
        try:
            code = int(code_text.strip())
        except ValueError as e:
            raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from e
        if code == _NO_ERROR_CODE:
            return errors
        errors.append(response)


def _wait_for_operation_complete(session) -> None:
    """Step 6 of the measurement sequence: query *OPC? until it returns 1."""
    for _ in range(_OPC_POLL_LIMIT):
        if session.query("*OPC?").strip() == "1":
            return
    raise InstrumentError("*OPC? did not return 1: the measurement did not complete")


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.

    Follows the required sequence of MANUAL.md section 3. Two points from the manual drive the
    structure: FETC? never measures (it returns the last completed INIT, or -100.00 dBm after
    reset), so INIT and *OPC? always come before FETC?; and a refused setting (for example a
    frequency outside 10 MHz to 18 GHz) is only reported through the error queue, so the queue is
    drained before the reading is trusted.
    """
    # 1. Clear the error queue so that anything found at the end belongs to this measurement.
    session.write("*CLS")

    # 2. Signal frequency in Hz. repr() keeps full precision; the meter accepts plain numbers and
    #    scientific notation. Out-of-band values are refused with -222 and caught in step 8.
    session.write(f"SENS:FREQ {float(freq_hz)!r}")

    # 3. Averaging count. Sent as given so that a non-integer or out-of-range value is refused by
    #    the meter (-104 / -222) rather than silently coerced here.
    session.write(f"SENS:AVER:COUN {averages}")

    # 4. Auto range: LOW below -20 dBm, HIGH otherwise.
    session.write("CONF:POW:RANG AUTO")

    # 5. Start one measurement with the settings above.
    session.write("INIT")

    # 6. Wait until the measurement is complete.
    _wait_for_operation_complete(session)

    # 7. Fetch the measurement buffer, which now holds the reading from step 5.
    raw = session.query("FETC?").strip()

    # 8. Drain the error queue. Any entry means a setting was refused or the reading is not valid
    #    (for example 201 with the +9.90E+37 over-range marker), so the reading must not be used.
    errors = _drain_errors(session)
    if errors:
        raise InstrumentError("; ".join(errors))

    try:
        return float(raw)
    except ValueError as e:
        raise InstrumentError(f"unparseable FETC? response: {raw!r}") from e
