"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    session.write("*CLS")
    session.write("SENS:FREQ %s" % repr(float(freq_hz)))
    session.write("SENS:AVER:COUN %s" % (averages,))
    session.write("CONF:POW:RANG AUTO")
    session.write("INIT")
    session.query("*OPC?")  # blocks until the measurement is complete
    reply = session.query("FETC?")

    # Drain the whole error queue (it holds at most 10 entries).
    errors = []
    for _ in range(12):
        code, _, text = session.query("SYST:ERR?").strip().partition(",")
        if int(code) == 0:
            break
        errors.append("%s,%s" % (code.strip(), text.strip()))
    if errors:
        raise InstrumentError("; ".join(errors))

    return float(reply)
