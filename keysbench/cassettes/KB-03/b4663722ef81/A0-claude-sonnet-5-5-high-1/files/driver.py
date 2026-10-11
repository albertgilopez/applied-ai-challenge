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
    if averages == int(averages):
        averages = int(averages)

    session.write("*CLS")
    session.write("SENS:FREQ %.12g" % freq_hz)
    session.write("SENS:AVER:COUN %s" % averages)
    session.write("CONF:POW:RANG AUTO")
    session.write("INIT")
    opc = session.query("*OPC?").strip()
    reading = session.query("FETC?").strip()

    errors = []
    for _ in range(12):
        err = session.query("SYST:ERR?").strip()
        code = err.split(",", 1)[0].strip()
        try:
            is_none = int(code) == 0
        except ValueError:
            is_none = False
        if is_none:
            break
        errors.append(err)
    if errors:
        raise InstrumentError("; ".join(errors))

    if opc != "1":
        raise InstrumentError("measurement did not complete: *OPC? returned %r" % opc)
    try:
        value = float(reading)
    except ValueError:
        raise InstrumentError("unparseable reading: %r" % reading)
    return value
