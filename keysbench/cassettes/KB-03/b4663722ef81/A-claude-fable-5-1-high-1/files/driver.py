"""Driver for the Brevalt KX-100 RF power meter. The programming manual is MANUAL.md.

`session` is an open connection to the meter with three methods:
    session.write(cmd: str) -> None
    session.read() -> str
    session.query(cmd: str) -> str      # write, then read
"""


class InstrumentError(Exception):
    """The meter reported an error: SYST:ERR? returned a code other than 0."""


_NO_ERROR_CODE = 0
_OVER_RANGE_DBM = 9.0e37  # FETC? returns +9.90E+37 when the input exceeds the selected range
_MAX_OPC_POLLS = 1000
_ERROR_QUEUE_DEPTH = 10  # the meter queues at most 10 errors (plus the -350 overflow marker)


def _drain_errors(session) -> list[tuple[int, str]]:
    """Read SYST:ERR? until the queue is empty; return every error reported, oldest first."""
    errors = []
    for _ in range(_ERROR_QUEUE_DEPTH + 2):
        response = session.query("SYST:ERR?")
        code_text, _, text = response.partition(",")
        code = int(code_text)
        if code == _NO_ERROR_CODE:
            return errors
        errors.append((code, text.strip().strip('"')))
    return errors


def measure_power(session, freq_hz: float, averages: int) -> float:
    """Measure the power of a signal at `freq_hz`, averaging `averages` readings, and return it in dBm.

    Raise InstrumentError if the meter reports any error while configuring or measuring.
    """
    # 1. Start from an empty error queue so that anything reported afterwards is ours.
    session.write("*CLS")

    # 2-4. Configure: frequency (selects the calibration factor), averaging count, auto range.
    #      Out-of-range values are refused by the meter with an error code, caught in step 8.
    session.write(f"SENS:FREQ {float(freq_hz):.9E}")
    session.write(f"SENS:AVER:COUN {averages}")
    session.write("CONF:POW:RANG AUTO")

    # 5-6. Trigger one measurement and wait until it has completed. FETC? never measures by
    #      itself; without INIT it would return the stale buffer (-100.00 dBm after reset).
    session.write("INIT")
    for _ in range(_MAX_OPC_POLLS):
        if session.query("*OPC?").strip() == "1":
            break
    else:
        raise InstrumentError("measurement did not complete (*OPC? never returned 1)")

    # 7. Fetch the result of that INIT.
    raw = session.query("FETC?").strip()
    try:
        value_dbm = float(raw)
    except ValueError as e:
        raise InstrumentError(f"unparseable FETC? response: {raw!r}") from e

    # 8. Any queued error means a setting was refused or the reading is not valid.
    errors = _drain_errors(session)
    if errors:
        detail = "; ".join(f'{code},"{text}"' for code, text in errors)
        raise InstrumentError(f"meter reported error(s): {detail}")
    if value_dbm >= _OVER_RANGE_DBM:
        raise InstrumentError(f"measurement over range: FETC? returned {raw}")

    return value_dbm
