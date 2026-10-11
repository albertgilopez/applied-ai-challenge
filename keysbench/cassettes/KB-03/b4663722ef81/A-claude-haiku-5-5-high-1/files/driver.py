"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


import operator


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


# The error queue holds 10 entries (MANUAL.md section 8); allow a few extra reads so that a
# queue which never empties is reported instead of looping forever.
_MAX_ERROR_READS = 16
# Over-range sentinel returned by FETC? (MANUAL.md section 2, "Ranges").
_OVER_RANGE_DBM = 9.9e37


def _drain_error_queue(session) -> None:
    """Read SYST:ERR? until it reports 0 ("No error"); raise InstrumentError listing anything queued."""
    found: list[str] = []
    for _ in range(_MAX_ERROR_READS):
        response = session.query("SYST:ERR?")
        code_text, _, text = response.partition(",")
        try:
            code = int(code_text.strip())
        except ValueError:
            raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from None
        if code == 0:
            break
        found.append(f"{code} {text.strip()}")
    else:
        found.append("error queue did not empty")
    if found:
        raise InstrumentError("; ".join(found))


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    freq = float(freq_hz)
    count = operator.index(averages)  # rejects non-integers instead of silently truncating

    # Clear stale errors, then configure. Frequency is sent as a plain integer number of Hz.
    session.write("*CLS")
    session.write(f"SENS:FREQ {freq:.0f}")
    session.write(f"SENS:AVER:COUN {count}")
    session.write("CONF:POW:RANG AUTO")
    # A refused setting (e.g. -222 for an out-of-band frequency) keeps the previous value; do not
    # measure with it.
    _drain_error_queue(session)

    # FETC? only returns the buffer of the last completed INIT, so measure first.
    session.write("INIT")
    if session.query("*OPC?").strip() != "1":
        raise InstrumentError("measurement did not complete: *OPC? did not return 1")

    response = session.query("FETC?")
    # Any error queued by the measurement (e.g. 201 over-range) makes the reading invalid.
    _drain_error_queue(session)

    try:
        value = float(response)
    except ValueError:
        raise InstrumentError(f"unparseable FETC? response: {response!r}") from None
    if value != value or value >= _OVER_RANGE_DBM:
        raise InstrumentError(f"no valid reading: FETC? returned {response!r}")
    return value
