"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


def _check_errors(session) -> None:
    errors = []
    while True:
        reply = session.query("SYST:ERR?")
        code = int(reply.split(",", 1)[0])
        if code == 0:
            break
        errors.append(reply)
    if errors:
        raise InstrumentError("; ".join(errors))


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    session.write("*CLS")
    session.write(f"SENS:FREQ {freq_hz:.0f}")
    session.write(f"SENS:AVER:COUN {int(averages)}")
    session.write("CONF:POW:RANG AUTO")
    _check_errors(session)
    session.write("INIT")
    session.query("*OPC?")
    value = float(session.query("FETC?"))
    _check_errors(session)
    return value
