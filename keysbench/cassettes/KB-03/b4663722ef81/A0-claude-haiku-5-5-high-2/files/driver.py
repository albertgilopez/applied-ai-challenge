"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


import operator


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


# The meter's error queue holds 10 entries; this bounds the SYST:ERR? reads so that a session that
# never answers 0 cannot loop forever.
_ERROR_READ_LIMIT = 32


def _check_errors(session) -> None:
    """Drain the error queue with SYST:ERR? until it reports 0; raise InstrumentError if anything was queued.

    The queue is always read to empty, so no stale error leaks into the next call.
    """
    found: list[str] = []
    for _ in range(_ERROR_READ_LIMIT):
        response = session.query("SYST:ERR?")
        code_text, _, text = response.partition(",")
        try:
            code = int(code_text)
        except ValueError:
            raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from None
        if code == 0:
            if found:
                raise InstrumentError("; ".join(found))
            return
        found.append(f"{code} {text.strip()}")
    raise InstrumentError("error queue did not empty: " + "; ".join(found))


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    freq = float(freq_hz)
    count = operator.index(averages)  # integer count only; a float such as 16.0 is a caller error

    # Start from a clean error queue, then configure. The frequency must be the signal's: the meter
    # applies the calibration factor of the frequency it is set to.
    session.write("*CLS")
    session.write(f"SENS:FREQ {freq:.0f}")
    session.write(f"SENS:AVER:COUN {count}")
    session.write("CONF:POW:RANG AUTO")
    # A refused setting keeps the previous value, so check before measuring.
    _check_errors(session)

    # INIT starts the measurement; FETC? only returns the buffer of the last completed INIT.
    session.write("INIT")
    if session.query("*OPC?").strip() != "1":
        raise InstrumentError("measurement did not complete (*OPC? did not return 1)")
    text = session.query("FETC?")

    # The reading is valid only if no error was queued by the measurement (e.g. error 201, over range).
    _check_errors(session)
    return float(text)
