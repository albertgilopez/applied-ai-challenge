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


# Error-queue depth of the meter (MANUAL.md section 8); bounds the SYST:ERR? drain loop.
_ERROR_QUEUE_SIZE = 10
_OPC_POLLS = 100
_OVER_RANGE_DBM = 9.9e37  # value FETC? returns after an over-range measurement (error 201)


def _drain_errors(session) -> None:
    """Read SYST:ERR? until it reports 0,"No error". Raise InstrumentError if any error was queued."""
    found: list[str] = []
    for _ in range(_ERROR_QUEUE_SIZE + 2):
        response = session.query("SYST:ERR?")
        try:
            code = int(response.split(",", 1)[0].strip())
        except ValueError:
            found.append(response)
            continue
        if code == 0:
            break
        found.append(response)
    else:
        raise InstrumentError(f"error queue did not empty: {found}")
    if found:
        raise InstrumentError("; ".join(found))


def _wait_complete(session) -> None:
    """Poll *OPC? until the pending measurement has completed."""
    for _ in range(_OPC_POLLS):
        if session.query("*OPC?").strip() == "1":
            return
    raise InstrumentError("measurement did not complete")


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    count = operator.index(averages)  # rejects non-integers instead of silently truncating
    freq = f"{float(freq_hz):.0f}"  # plain Hz, no suffix or exponent

    # Start from a known state: *RST restores defaults (it does not clear the error queue, so *CLS follows).
    session.write("*RST")
    session.write("*CLS")
    # The meter cannot detect the signal frequency; it applies the calibration factor of SENS:FREQ.
    session.write(f"SENS:FREQ {freq}")
    session.write(f"SENS:AVER:COUN {count}")
    session.write("CONF:POW:RANG AUTO")
    _drain_errors(session)  # a refused setting must stop us before INIT

    session.write("INIT")  # FETC? never measures; INIT is what takes the reading
    _wait_complete(session)
    text = session.query("FETC?")
    _drain_errors(session)  # any error, including 201 from INIT, means the reading is not valid

    value = float(text)
    if not math.isfinite(value) or value >= _OVER_RANGE_DBM:
        raise InstrumentError(f"invalid reading {text!r}")
    return value
