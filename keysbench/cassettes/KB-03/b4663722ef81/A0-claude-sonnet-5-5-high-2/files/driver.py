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
    if int(averages) != averages:
        raise InstrumentError(f"-104,\"Data type error\": averaging count {averages!r} is not an integer")
    freq = float(freq_hz)
    freq_str = str(int(freq)) if freq == int(freq) else repr(freq)

    session.write("*CLS")
    session.write(f"SENS:FREQ {freq_str}")
    session.write(f"SENS:AVER:COUN {int(averages)}")
    session.write("CONF:POW:RANG AUTO")
    session.write("INIT")
    if session.query("*OPC?").strip() != "1":
        raise InstrumentError("measurement did not complete")
    reply = session.query("FETC?")

    # Drain the whole error queue (it holds at most 10 entries, plus overflow).
    errors = []
    for _ in range(20):
        err = session.query("SYST:ERR?").strip()
        code = err.split(",", 1)[0].strip()
        try:
            if int(code) == 0:
                break
        except ValueError:
            pass
        errors.append(err)
    else:
        errors.append("error queue did not empty")
    if errors:
        raise InstrumentError("; ".join(errors))

    try:
        value = float(reply)
    except ValueError:
        raise InstrumentError(f"unparseable reading: {reply!r}")
    return value
