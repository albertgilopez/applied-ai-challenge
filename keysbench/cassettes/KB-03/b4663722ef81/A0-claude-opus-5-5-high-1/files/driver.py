"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""

import math
import operator


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    # Sequence of MANUAL.md section 3.
    session.write("*CLS")  # start from an empty error queue
    session.write(f"SENS:FREQ {_format_number(freq_hz)}")
    session.write(f"SENS:AVER:COUN {_format_count(averages)}")
    session.write("CONF:POW:RANG AUTO")
    # A refused setting is kept at its previous value (-222 etc.); do not measure with it.
    _check_errors(session)

    session.write("INIT")
    opc = session.query("*OPC?").strip()
    if opc != "1":
        _check_errors(session)
        raise InstrumentError(f"*OPC? returned {opc!r} instead of '1'")
    response = session.query("FETC?").strip()
    # Any queued error (e.g. 201 over range) invalidates the reading.
    _check_errors(session)

    try:
        value = float(response)
    except ValueError as e:
        raise InstrumentError(f"FETC? returned an unparsable reading: {response!r}") from e
    if not math.isfinite(value) or abs(value) >= 9.9e37:
        raise InstrumentError(f"FETC? returned an invalid reading: {response!r}")
    return value


_ERROR_QUEUE_SIZE = 10


def _format_number(value) -> str:
    """Plain decimal/scientific number in Hz, accepted by the meter (no locale, no numpy repr)."""
    return repr(float(value))


def _format_count(value) -> str:
    """Integer averaging count; a non-integer is sent as is and the meter refuses it (-104)."""
    try:
        return str(operator.index(value))
    except TypeError:
        number = float(value)
        return str(int(number)) if number.is_integer() else repr(number)


def _check_errors(session) -> None:
    """Drain SYST:ERR? until "0,..."; raise InstrumentError listing every error found."""
    errors = []
    # The queue holds at most 10 entries; a few extra reads guard against a misbehaving meter.
    for _ in range(_ERROR_QUEUE_SIZE + 5):
        response = session.query("SYST:ERR?").strip()
        code_text, _, message = response.partition(",")
        try:
            code = int(code_text.strip())
        except ValueError as e:
            raise InstrumentError(f"unparsable SYST:ERR? response: {response!r}") from e
        if code == 0:
            break
        errors.append(f"{code},{message.strip()}")
    else:
        errors.append("error queue did not empty")
    if errors:
        raise InstrumentError("meter reported: " + "; ".join(errors))
