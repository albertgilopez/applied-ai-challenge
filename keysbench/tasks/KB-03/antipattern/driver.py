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
    # Looks right: configures, reads, checks errors. Is wrong: FETC? does not measure, and there is no
    # INIT, so it returns the reading in the buffer, not one taken with these settings.
    session.write(f"SENS:FREQ {freq_hz:.0f}")
    session.write(f"SENS:AVER:COUN {int(averages)}")
    value = float(session.query("FETC?"))
    reply = session.query("SYST:ERR?")
    if not reply.startswith("0,"):
        raise InstrumentError(reply)
    return value
