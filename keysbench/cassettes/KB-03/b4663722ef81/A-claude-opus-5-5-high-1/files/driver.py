"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""

import math

# The error queue holds 10 entries (MANUAL.md section 8); allow some margin before giving up.
_MAX_ERROR_READS = 32
# FETC? returns this value when the measurement over-ranged (MANUAL.md section 2, Ranges).
_OVER_RANGE = 9.9e37


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


def _drain_errors(session) -> list[str]:
    """Read SYST:ERR? until the queue is empty; return every non-zero entry, oldest first."""
    errors = []
    for _ in range(_MAX_ERROR_READS):
        reply = session.query("SYST:ERR?").strip()
        code_text = reply.split(",", 1)[0].strip()
        try:
            code = int(code_text)
        except ValueError:
            raise InstrumentError(f"unparseable SYST:ERR? reply: {reply!r}") from None
        if code == 0:
            return errors
        errors.append(reply)
    raise InstrumentError(f"error queue did not empty after {_MAX_ERROR_READS} reads: {errors}")


def _check_errors(session, stage: str) -> None:
    errors = _drain_errors(session)
    if errors:
        raise InstrumentError(f"KX-100 reported error(s) while {stage}: " + "; ".join(errors))


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    # 1. Start from an empty error queue so that any error seen later is ours.
    session.write("*CLS")

    # 2-4. Configure. Values are sent as given; the meter validates them (-104, -222, ...).
    session.write(f"SENS:FREQ {float(freq_hz)!r}")
    session.write(f"SENS:AVER:COUN {averages}")
    session.write("CONF:POW:RANG AUTO")
    _check_errors(session, "configuring")

    # 5-6. Take one new measurement and wait for it to complete. FETC? alone never measures.
    session.write("INIT")
    opc = session.query("*OPC?").strip()
    if opc != "1":
        raise InstrumentError(f"unexpected *OPC? reply: {opc!r}")

    # 7. Read the result.
    reply = session.query("FETC?").strip()

    # 8. Any error (e.g. 201 over range) invalidates the reading.
    _check_errors(session, "measuring")

    try:
        value = float(reply)
    except ValueError:
        raise InstrumentError(f"unparseable FETC? reply: {reply!r}") from None
    if not math.isfinite(value) or value >= _OVER_RANGE:
        raise InstrumentError(f"invalid reading: {reply!r}")
    return value
