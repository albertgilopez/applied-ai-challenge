"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""

import operator


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


_ERROR_READ_LIMIT = 20  # the meter's queue holds 10 entries; bounds the drain loop
_COMPLETE_POLL_LIMIT = 100  # bounds the *OPC? wait


def _drain_errors(session) -> None:
    """Read SYST:ERR? until the queue is empty. Raise InstrumentError if any entry is not 0."""
    found: list[str] = []
    for _ in range(_ERROR_READ_LIMIT):
        response = session.query("SYST:ERR?")
        code_text, _, text = response.partition(",")
        try:
            code = int(code_text)
        except ValueError:
            raise InstrumentError(f"unreadable error response: {response!r}") from None
        if code == 0:
            if found:
                raise InstrumentError("; ".join(found))
            return
        found.append(f"{code} {text.strip()}")
    raise InstrumentError("error queue did not empty: " + "; ".join(found))


def _wait_complete(session) -> None:
    """Poll *OPC? until the meter reports the pending measurement is complete."""
    for _ in range(_COMPLETE_POLL_LIMIT):
        if session.query("*OPC?").strip() == "1":
            return
    raise InstrumentError("meter did not report operation complete")


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    count = operator.index(averages)  # an integer count: rejects 16.0 instead of sending "16.0"
    session.write("*CLS")  # clear the queue so only errors from this call are reported
    session.write(f"SENS:FREQ {freq_hz:.0f}")  # plain number of Hz; sets the calibration factor
    session.write(f"SENS:AVER:COUN {count:d}")
    session.write("CONF:POW:RANG AUTO")
    _drain_errors(session)  # a refused setting makes the measurement invalid: stop before INIT
    session.write("INIT")
    _wait_complete(session)  # FETC? returns the previous buffer until the measurement completes
    response = session.query("FETC?")
    _drain_errors(session)  # e.g. 201 over range: the buffer then holds 9.90E+37, not a reading
    return float(response)
