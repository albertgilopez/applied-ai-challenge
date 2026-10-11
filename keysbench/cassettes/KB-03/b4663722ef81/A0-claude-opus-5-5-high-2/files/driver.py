"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


import math

# FETC? returns this value when the measurement over-ranged (MANUAL.md, "Ranges").
_OVER_RANGE = 9.9e37

# The error queue holds 10 entries (MANUAL.md section 8); this bound only guards against a
# misbehaving session that never reports an empty queue.
_MAX_ERROR_READS = 64


def _format_number(value) -> str:
    """Format a numeric parameter for the meter: integers without a decimal point, floats exactly.

    Values that are not numbers are sent as text; the meter refuses them and the refusal is
    reported as InstrumentError like any other error.
    """
    if isinstance(value, int):
        return str(value)  # bool becomes "True"/"False", which the meter refuses
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return repr(number)  # round-trips exactly; NaN/inf are sent as-is and refused by the meter


def _drain_errors(session) -> list:
    """Read SYST:ERR? until the queue is empty and return the non-zero entries, oldest first."""
    errors = []
    for _ in range(_MAX_ERROR_READS):
        response = session.query("SYST:ERR?").strip()
        code_text, _, message = response.partition(",")
        try:
            code = int(code_text.strip())
        except ValueError:
            raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from None
        if code == 0:
            return errors
        errors.append((code, message.strip().strip('"')))
    raise InstrumentError(f"error queue never emptied; errors so far: {errors}")


def _check_errors(session, stage: str) -> None:
    errors = _drain_errors(session)
    if errors:
        listed = "; ".join(f'{code},"{text}"' for code, text in errors)
        raise InstrumentError(f"KX-100 reported error(s) while {stage}: {listed}")


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.

    Follows the required measurement sequence of MANUAL.md section 3. Every setting is written
    explicitly and a fresh INIT is always taken before FETC?, because FETC? only returns the
    buffer of the last completed INIT (or -100.00 dBm after *RST).
    """
    freq_arg = _format_number(freq_hz)
    aver_arg = _format_number(averages)

    # 1. Start from a clean error queue so any error seen later belongs to this measurement.
    session.write("*CLS")

    # 2-4. Configure. The meter cannot detect the signal frequency, so it must be set.
    session.write(f"SENS:FREQ {freq_arg}")
    session.write(f"SENS:AVER:COUN {aver_arg}")
    session.write("CONF:POW:RANG AUTO")
    # A refused setting keeps the previous value; do not measure with it.
    _check_errors(session, "configuring")

    # 5-6. Take one measurement and wait for it to complete.
    session.write("INIT")
    opc = session.query("*OPC?").strip()
    if opc != "1":
        _check_errors(session, "measuring")
        raise InstrumentError(f"unexpected *OPC? response: {opc!r}")

    # 7. Fetch the result of that measurement.
    response = session.query("FETC?").strip()

    # 8. Any queued error (e.g. 201 over-range) invalidates the reading.
    _check_errors(session, "measuring")

    try:
        value = float(response)
    except ValueError:
        raise InstrumentError(f"unparseable FETC? response: {response!r}") from None
    if not math.isfinite(value) or value >= _OVER_RANGE:
        raise InstrumentError(f"measurement over range (FETC? returned {response!r})")
    return value
