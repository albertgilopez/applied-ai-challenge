"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


_ERROR_QUEUE_SIZE = 10  # MANUAL.md section 8
_OVER_RANGE = 9.9e37  # FETC? value on over-range (MANUAL.md section 2, Ranges)


def _parse_error(response: str) -> tuple[int, str]:
    """Split a SYST:ERR? response `code,"text"` into (code, text)."""
    code_part, _, text = response.strip().partition(",")
    try:
        code = int(code_part.strip())
    except ValueError as e:
        raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from e
    return code, text.strip().strip('"')


def _drain_errors(session) -> list[tuple[int, str]]:
    """Read SYST:ERR? until it returns 0 and return every error read, oldest first."""
    errors: list[tuple[int, str]] = []
    # The queue holds at most 10 entries; allow a margin, but never loop forever.
    for _ in range(2 * _ERROR_QUEUE_SIZE + 1):
        code, text = _parse_error(session.query("SYST:ERR?"))
        if code == 0:
            return errors
        errors.append((code, text))
    raise InstrumentError(f"error queue does not empty; errors read: {errors}")


def _check_errors(session, stage: str) -> None:
    errors = _drain_errors(session)
    if errors:
        listed = "; ".join(f'{code},"{text}"' for code, text in errors)
        raise InstrumentError(f"KX-100 reported error(s) {stage}: {listed}")


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    # 1. Known state: defaults (also loads the -100 dBm reset reading, so an old measurement can
    #    never be returned) and an empty error queue.
    session.write("*RST")
    session.write("*CLS")

    # 2-4. Configure. Values are sent as given; the meter validates them (-104, -222, ...).
    session.write(f"SENS:FREQ {float(freq_hz)!r}")
    session.write(f"SENS:AVER:COUN {averages}")
    session.write("CONF:POW:RANG AUTO")
    # A refused setting would make the measurement invalid: stop before measuring.
    _check_errors(session, "while configuring")

    # 5-7. Take one fresh measurement, wait for it, then fetch it.
    session.write("INIT")
    opc = session.query("*OPC?").strip()
    if opc != "1":
        raise InstrumentError(f"unexpected *OPC? response: {opc!r}")
    response = session.query("FETC?").strip()

    # 8. Any error (e.g. 201 over range) means the reading must not be used.
    _check_errors(session, "while measuring")

    try:
        value = float(response)
    except ValueError as e:
        raise InstrumentError(f"unparseable FETC? response: {response!r}") from e
    if value >= _OVER_RANGE or value != value:
        raise InstrumentError(f"invalid reading from FETC?: {response!r}")
    return value
