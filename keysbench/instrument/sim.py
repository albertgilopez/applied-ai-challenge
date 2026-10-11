"""KX-100 RF power meter: an in-process simulator of a fictitious SCPI instrument.

KeysBench's domain tasks (KB-03..KB-06) are written against this instrument because it is in no
training set: its command set is public-shaped SCPI and its specification table is ordinary GUM,
but its numbers and its traps exist only here and in ``MANUAL.md``.

Session (SCPI surface, what a driver sees)
    ``write(cmd)``, ``read() -> str``, ``query(cmd) -> str``. One command per write; a trailing
    ``"\\n"`` (the termination character) is accepted and removed, and responses are returned
    without it. ``read()`` with nothing pending queues ``-420`` and raises :class:`KX100Timeout`.
    Writing while an answer is unread discards the answer and queues ``-410``.

Reading model (deterministic for a seed)
    The hidden input is a signal of ``true_power_dbm`` at ``signal_hz``. ``INIT`` takes measurement
    number ``i`` of the session::

        P_in   = 10 ** (true_power_dbm / 10) / 1000                       # W
        P_corr = P_in * CF(signal_hz) / CF(SENS:FREQ) + ZERO_OFFSET_W[range]
        P_meas = P_corr * (1 + NOISE_REL_N1 / sqrt(SENS:AVER:COUN) * z_i)
        reading_dbm = round(10 * log10(1000 * P_meas), 2)

    ``CF`` is the sensor calibration factor, interpolated linearly in frequency from
    :data:`CAL_FACTOR_PCT`: the meter corrects with the factor of the frequency it is *set* to, so
    a driver that does not set the signal frequency reads ``CF(signal)/CF(set)`` off. ``z_i`` is a
    standard normal drawn from ``(seed, i)`` and clamped to +-3, so two sessions with the same seed
    see the same ``z`` on the same measurement and averaging only ever shrinks it. ``AUTO`` range
    is LOW below -20 dBm input, HIGH otherwise; each range adds its own small zero offset.

    ``FETC?`` returns the measurement buffer: the last completed ``INIT``, or
    :data:`RESET_READING_DBM` after power-on and ``*RST``. It never measures. That is the trap of
    KB-03's antipattern; every such read is counted in ``stale_fetches``.

Test-only surface (never in the manual): ``true_power_dbm``, ``signal_hz``, ``expected_dbm()``,
``stale_fetches`` and ``commands``. Graders use them as the oracle; a driver must not.
"""

from __future__ import annotations

import math
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

MANUAL_PATH = Path(__file__).with_name("MANUAL.md")

# Declared limits. KB-05 requires the contestant's quote to contain one of these strings, so each
# appears verbatim, on its own line, in MANUAL.md (a test checks it). No trailing period on purpose.
LIMIT_LINES: tuple[str, ...] = (
    "Measurement resolution: 0.01 dB",
    "Frequency range: 10 MHz to 18 GHz",
    "Power range: -60 dBm to +20 dBm",
)

# Specification table for a first-order GUM budget (KB-04). Each row is written in MANUAL.md as
# "| a | b | c | d | e |"; a test checks every row is there exactly.
SPEC_TABLE_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ("Instrument accuracy", "±0.50", "% of reading", "rectangular", "√3"),
    ("Linearity", "±0.30", "% of reading", "rectangular", "√3"),
    ("Zero offset, LOW range", "±0.5", "nW", "rectangular", "√3"),
    ("Zero offset, HIGH range", "±50", "nW", "rectangular", "√3"),
    ("Calibration factor, 10 MHz to 8 GHz", "±1.6", "% of reading, expanded (k = 2)", "normal", "2"),
    ("Calibration factor, above 8 GHz to 18 GHz", "±2.2", "% of reading, expanded (k = 2)", "normal", "2"),
    ("Noise, averaging count N", "2.0 / √N", "% of reading, one standard deviation", "normal", "1"),
    ("Mismatch", "±200·Γs·Γm", "% of reading (Γs, Γm: reflection coefficient magnitudes)", "U-shaped", "√2"),
    ("Display resolution", "±0.005", "dB (half of the 0.01 dB step)", "rectangular", "√3"),
)

# The same numbers, for code that builds a reference (KB-04). Must agree with SPEC_TABLE_ROWS.
SPEC: dict[str, object] = {
    "accuracy_pct": 0.50,
    "linearity_pct": 0.30,
    "zero_offset_nw": {"LOW": 0.5, "HIGH": 50.0},
    "cal_factor_pct_k2": ((8e9, 1.6), (18e9, 2.2)),  # (upper frequency inclusive, value)
    "noise_pct_n1": 2.0,
    "gamma_meter": ((8e9, 0.10), (18e9, 0.15)),
    "resolution_db": 0.01,
}

# Documented commands (short forms). Every one must appear in MANUAL.md (a test checks it).
COMMANDS: tuple[str, ...] = (
    "*IDN?",
    "*RST",
    "*CLS",
    "*OPC?",
    "SYST:ERR?",
    "SENS:FREQ",
    "SENS:AVER:COUN",
    "CONF:POW:RANG",
    "INIT",
    "FETC?",
)

MAKER = "Kestrel Microwave"
MODEL = "KX-100"
FIRMWARE = "1.02"

FREQ_MIN_HZ = 10e6
FREQ_MAX_HZ = 18e9
POWER_MIN_DBM = -60.0
POWER_MAX_DBM = 20.0
AVER_MIN, AVER_MAX = 1, 1024
RANGES = ("AUTO", "LOW", "HIGH")
LOW_RANGE_MAX_DBM = -10.0
AUTO_LOW_BELOW_DBM = -20.0

RST_FREQ_HZ = 50e6
RST_AVER = 1
RST_RANGE = "AUTO"
RESET_READING_DBM = -100.0
OVER_RANGE = 9.9e37

NOISE_REL_N1 = 0.02
Z_CLAMP = 3.0
# Actual offsets of the simulated unit, inside the specified bounds (0.5 nW, 50 nW).
ZERO_OFFSET_W = {"LOW": 0.2e-9, "HIGH": 20e-9}

# Sensor calibration factor, % (reference 100.0 at 50 MHz).
CAL_FACTOR_PCT: tuple[tuple[float, float], ...] = (
    (10e6, 98.6),
    (50e6, 100.0),
    (100e6, 99.8),
    (1e9, 99.1),
    (2e9, 98.4),
    (4e9, 97.5),
    (6e9, 96.7),
    (8e9, 95.8),
    (10e9, 94.9),
    (12e9, 93.7),
    (14e9, 92.6),
    (16e9, 91.4),
    (18e9, 90.1),
)

ERROR_TEXT = {
    -104: "Data type error",
    -108: "Parameter not allowed",
    -109: "Missing parameter",
    -113: "Undefined header",
    -131: "Invalid suffix",
    -222: "Data out of range",
    -224: "Illegal parameter value",
    -350: "Queue overflow",
    -410: "Query INTERRUPTED",
    -420: "Query UNTERMINATED",
    201: "Measurement over range",
}
ERROR_QUEUE_SIZE = 10

_FREQ_SUFFIX = {"": 1, "HZ": 1, "KHZ": 10**3, "MHZ": 10**6, "GHZ": 10**9}
_NUMBER = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z]*)$")

# Command tree, long forms with the short form in capitals (SCPI convention).
_TREE: dict[tuple[str, ...], str] = {
    ("SENSe", "FREQuency"): "freq",
    ("SENSe", "AVERage", "COUNt"): "aver",
    ("CONFigure", "POWer", "RANGe"): "range",
    ("SYSTem", "ERRor"): "err",
    ("INITiate",): "init",
    ("FETCh",): "fetch",
}


class KX100Timeout(Exception):
    """``read()`` was called with no response pending (the session would block until timeout)."""


class _CommandError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def dbm_to_w(dbm: float) -> float:
    return float(10 ** (dbm / 10) / 1000)


def w_to_dbm(watts: float) -> float:
    return 10 * math.log10(1000 * watts)


def cal_factor_pct(freq_hz: float) -> float:
    """Calibration factor at ``freq_hz``, linear interpolation in frequency over the table."""
    points = CAL_FACTOR_PCT
    if freq_hz <= points[0][0]:
        return points[0][1]
    for (f0, c0), (f1, c1) in zip(points, points[1:], strict=False):
        if freq_hz <= f1:
            return c0 + (c1 - c0) * (freq_hz - f0) / (f1 - f0)
    return points[-1][1]


def _matches(token: str, mnemonic: str) -> bool:
    short = "".join(ch for ch in mnemonic if ch.isupper())
    return token.upper() in (short, mnemonic.upper())


def _lookup(header: str) -> str | None:
    parts = header.lstrip(":").split(":")
    for path, name in _TREE.items():
        if len(path) == len(parts) and all(_matches(t, m) for t, m in zip(parts, path, strict=True)):
            return name
    return None


class KX100:
    """One open session to a simulated KX-100 with a hidden input signal."""

    def __init__(self, seed: int = 0, *, signal_hz: float | None = None, signal_dbm: float | None = None) -> None:
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        rng = random.Random(f"kx100-signal:{seed}")
        default_hz = round(rng.uniform(6e9, FREQ_MAX_HZ) / 1e6) * 1e6
        default_dbm = round(rng.uniform(-30.0, 0.0), 3)
        self.seed = seed
        self.signal_hz = float(default_hz if signal_hz is None else signal_hz)
        self.true_power_dbm = float(default_dbm if signal_dbm is None else signal_dbm)
        if not FREQ_MIN_HZ <= self.signal_hz <= FREQ_MAX_HZ:
            raise ValueError(f"signal_hz outside {FREQ_MIN_HZ:g}..{FREQ_MAX_HZ:g}")
        if not POWER_MIN_DBM <= self.true_power_dbm <= POWER_MAX_DBM:
            raise ValueError(f"signal_dbm outside {POWER_MIN_DBM:g}..{POWER_MAX_DBM:g}")
        self.commands: list[str] = []
        self.stale_fetches = 0
        self._errors: list[tuple[int, str]] = []
        self._pending: str | None = None
        self._measurements = 0
        self._reset()

    # --- SCPI session ---------------------------------------------------------------------------

    def write(self, cmd: str) -> None:
        line = cmd.rstrip("\n").strip()
        self.commands.append(line)
        if self._pending is not None:
            self._pending = None
            self._push(-410)
        if not line:
            return
        try:
            answer = self._execute(line)
        except _CommandError as e:
            self._push(e.code)
            return
        if answer is not None:
            self._pending = answer

    def read(self) -> str:
        if self._pending is None:
            self._push(-420)
            raise KX100Timeout("no response pending")
        answer, self._pending = self._pending, None
        return answer

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self.read()

    # --- test-only oracle -----------------------------------------------------------------------

    def expected_dbm(self, freq_hz: float | None = None, power_range: str = "AUTO") -> float:
        """Noiseless reading for the hidden signal with the given settings (default: signal frequency)."""
        f = self.signal_hz if freq_hz is None else freq_hz
        return w_to_dbm(self._corrected_w(f, self._resolve_range(power_range)))

    # --- internals ------------------------------------------------------------------------------

    def _reset(self) -> None:
        self._freq_hz = RST_FREQ_HZ
        self._aver = RST_AVER
        self._range = RST_RANGE
        self._buffer = RESET_READING_DBM
        self._fresh = False

    def _push(self, code: int) -> None:
        entry = (code, ERROR_TEXT[code])
        if len(self._errors) < ERROR_QUEUE_SIZE:
            self._errors.append(entry)
        else:
            self._errors[-1] = (-350, ERROR_TEXT[-350])

    def _execute(self, line: str) -> str | None:
        header, _, arg = line.partition(" ")
        arg = arg.strip()
        query = header.endswith("?")
        head = header[:-1] if query else header
        up = head.upper()

        if up.startswith("*"):
            return self._common(up, query, arg)

        name = _lookup(head)
        if name is None:
            raise _CommandError(-113)
        if name in ("err", "fetch") and not query:
            raise _CommandError(-113)
        if name == "init" and query:
            raise _CommandError(-113)
        if (query or name == "init") and arg:
            raise _CommandError(-108)
        if not query and name not in ("init",) and not arg:
            raise _CommandError(-109)

        if name == "err":
            code, text = self._errors.pop(0) if self._errors else (0, "No error")
            return f'{code},"{text}"'
        if name == "fetch":
            if not self._fresh:
                self.stale_fetches += 1
            return "+9.90E+37" if self._buffer == OVER_RANGE else f"{self._buffer:+.2f}"
        if name == "init":
            self._measure()
            return None
        if name == "freq":
            if query:
                return f"{self._freq_hz:+.9E}"
            self._freq_hz = self._parse_freq(arg)
            self._fresh = False
            return None
        if name == "aver":
            if query:
                return f"{self._aver:+d}"
            self._aver = self._parse_count(arg)
            self._fresh = False
            return None
        # range
        if query:
            return self._range
        value = arg.upper()
        if value not in RANGES:
            raise _CommandError(-224)
        self._range = value
        self._fresh = False
        return None

    def _common(self, up: str, query: bool, arg: str) -> str | None:
        known = {("*IDN", True), ("*RST", False), ("*CLS", False), ("*OPC", True)}
        if (up, query) not in known:
            raise _CommandError(-113)
        if arg:
            raise _CommandError(-108)
        if up == "*IDN":
            return f"{MAKER},{MODEL},KX{self.seed:06d},{FIRMWARE}"
        if up == "*OPC":
            return "1"
        if up == "*RST":
            self._reset()
            return None
        self._errors.clear()  # *CLS
        return None

    def _parse_number(self, arg: str, suffixes: dict[str, int]) -> float:
        m = _NUMBER.match(arg)
        if not m:
            raise _CommandError(-104)
        suffix = m.group(2).upper()
        if suffix not in suffixes:
            raise _CommandError(-131)
        try:
            return float(Decimal(m.group(1)) * suffixes[suffix])
        except InvalidOperation as e:  # pragma: no cover - the regex admits only valid decimals
            raise _CommandError(-104) from e

    def _parse_freq(self, arg: str) -> float:
        value = self._parse_number(arg, _FREQ_SUFFIX)
        if not FREQ_MIN_HZ <= value <= FREQ_MAX_HZ:
            raise _CommandError(-222)
        return value

    def _parse_count(self, arg: str) -> int:
        value = self._parse_number(arg, {"": 1})
        if not value.is_integer():
            raise _CommandError(-104)
        if not AVER_MIN <= value <= AVER_MAX:
            raise _CommandError(-222)
        return int(value)

    def _resolve_range(self, power_range: str) -> str:
        if power_range == "AUTO":
            return "LOW" if self.true_power_dbm < AUTO_LOW_BELOW_DBM else "HIGH"
        return power_range

    def _corrected_w(self, freq_hz: float, power_range: str) -> float:
        ratio = cal_factor_pct(self.signal_hz) / cal_factor_pct(freq_hz)
        return dbm_to_w(self.true_power_dbm) * ratio + ZERO_OFFSET_W[power_range]

    def _measure(self) -> None:
        self._measurements += 1
        self._fresh = True
        power_range = self._resolve_range(self._range)
        if power_range == "LOW" and self.true_power_dbm > LOW_RANGE_MAX_DBM:
            self._buffer = OVER_RANGE
            self._push(201)
            return
        z = random.Random(f"kx100-noise:{self.seed}:{self._measurements}").gauss(0.0, 1.0)
        z = max(-Z_CLAMP, min(Z_CLAMP, z))
        watts = self._corrected_w(self._freq_hz, power_range) * (1 + NOISE_REL_N1 / math.sqrt(self._aver) * z)
        self._buffer = round(w_to_dbm(watts), 2)
