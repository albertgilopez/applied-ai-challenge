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

    Follows the required measurement sequence of MANUAL.md section 3. Note that `FETC?` never
    measures by itself: it returns the buffer of the last completed `INIT`, so the meter is
    configured, triggered with `INIT` and waited on with `*OPC?` before the result is fetched.
    """
    # 1. Start from a clean error queue so that anything found afterwards belongs to this call.
    session.write("*CLS")

    # 2-4. Configure: signal frequency (selects the calibration factor), averaging count, range.
    session.write(f"SENS:FREQ {freq_hz!r}")
    session.write(f"SENS:AVER:COUN {averages}")
    session.write("CONF:POW:RANG AUTO")

    # 5-6. Trigger one measurement and wait for it to complete.
    session.write("INIT")
    _wait_for_opc(session)

    # 7. Fetch the result of that measurement.
    reading = session.query("FETC?").strip()

    # 8. Drain the error queue; any code other than 0 invalidates the reading.
    errors = _drain_errors(session)
    if errors:
        raise InstrumentError("; ".join(f'{code},"{text}"' for code, text in errors))

    try:
        return float(reading)
    except ValueError as e:
        raise InstrumentError(f"unparseable FETC? response: {reading!r}") from e


def _wait_for_opc(session) -> None:
    """Query *OPC? until the meter answers 1 (all pending operations, including INIT, complete)."""
    while session.query("*OPC?").strip() != "1":
        pass


def _drain_errors(session) -> list[tuple[int, str]]:
    """Read SYST:ERR? until it returns 0,"No error"; return the (code, text) pairs found."""
    errors: list[tuple[int, str]] = []
    while True:
        response = session.query("SYST:ERR?").strip()
        code_str, _, text = response.partition(",")
        try:
            code = int(code_str)
        except ValueError as e:
            raise InstrumentError(f"unparseable SYST:ERR? response: {response!r}") from e
        if code == 0:
            return errors
        errors.append((code, text.strip().strip('"')))
