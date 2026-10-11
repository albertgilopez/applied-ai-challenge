"""Copied by the grader next to the hidden tests; hidden tests import it. The contestant never sees or
edits it.

`call` runs the contestant's code in a separate, isolated Python process and returns its result parsed
from JSON. Nothing the contestant's code does in that process (patching the test runner, returning an
object that claims to equal anything, exiting early) reaches the test's own process: only plain JSON
comes back, and `strict_equal` compares it by type as well as value.

That process runs in a disposable container that holds only the code under test (the grading
directory's `code/`, mounted read-only): no network, no hidden tests, no reference values, no repository,
no credentials. On the first layout it ran on the host next to the tests, and a code review produced four
solutions that passed without solving the task: one read the hidden test's reference values, one imported
the benchmark's own solution through the interpreter's path, and two (KB-03) read the simulator's oracle
or forged the result line because the simulator shared their process. Expected values and oracles now
live only on the host; `drive` keeps the KB-03 simulator on the host and gives the driver a session over
a pipe.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

MARKER = "KBRESULT "
HERE = Path(__file__).resolve().parent
CODE = HERE.parent / "code"  # the grading directory's code under test; the tests are in HERE
# Pinned by digest: the interpreter that runs contestant code is the same on every machine and in CI.
IMAGE = "python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce"
RUN_ID = os.environ.get("KB_RUN_ID", "local")  # set by the grader, so a timeout can remove its containers


class CallFailed(AssertionError):
    pass


def container_command(code: str, *, interactive: bool = False) -> list[str]:
    name = f"kb-{RUN_ID}-{uuid.uuid4().hex[:10]}"
    return [
        "docker", "run", "--rm", *(["-i"] if interactive else []), "--name", name,
        "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=16m",
        "--memory", "512m", "--cpus", "1", "--pids-limit", "64", "--security-opt", "no-new-privileges",
        # Two guards against writing the code under test: a non-root user and a read-only mount. On Linux
        # either alone holds, so they are one line and one canary removes both.
        "--user", "65534:65534", "--mount", f"type=bind,source={CODE},target=/code,readonly",
        "-w", "/code", IMAGE,
        "python", "-I", "-B", "-c", code,
    ]  # fmt: skip


def _kill(cmd: list[str]) -> None:
    subprocess.run(["docker", "rm", "-f", cmd[cmd.index("--name") + 1]], capture_output=True, check=False)


def call(expression: str, *modules: str, setup: str = "", timeout_s: float = 60.0) -> Any:
    """Evaluate `expression` after importing `modules` from the code under test, in a fresh `python -I`
    inside the container. `setup` is run first (statements, e.g. a try/except that turns an expected
    exception into a value)."""
    imports = "".join(f"import {m}\n" for m in modules)
    code = (
        "import sys, json\n"
        "sys.path.insert(0, '/code')\n"
        f"{imports}"
        f"{setup}\n"
        f"_r = {expression}\n"
        f"sys.stdout.write({MARKER!r} + json.dumps(_r, allow_nan=False) + chr(10))\n"
    )
    cmd = container_command(code)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        _kill(cmd)
        raise CallFailed(f"no result within {timeout_s} s") from exc
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(MARKER)]
    if proc.returncode != 0 or len(lines) != 1:
        raise CallFailed(f"exit {proc.returncode}; stderr: {proc.stderr[-500:]}")
    return json.loads(lines[0][len(MARKER) :])


# ── a session over a pipe (KB-03): the simulator stays on the host ───────────────────────────────────

DRIVER = """
import json, sys
sys.path.insert(0, '/code')
_in, _out = sys.stdin, sys.stdout


def _ask(message):
    _out.write(json.dumps(message) + chr(10))
    _out.flush()
    reply = json.loads(_in.readline())
    if 'error' in reply:
        raise TimeoutError(reply['error'])
    return reply.get('value')


class Session:
    def write(self, cmd):
        _ask({'op': 'write', 'cmd': str(cmd)})

    def read(self):
        return _ask({'op': 'read'})

    def query(self, cmd):
        return _ask({'op': 'query', 'cmd': str(cmd)})


import driver
try:
    value = driver.measure_power(Session(), %(freq)r, %(n)r)
    result = {'op': 'result', 'kind': 'value', 'value': value}
    json.dumps(result, allow_nan=False)
except driver.InstrumentError as e:
    result = {'op': 'result', 'kind': 'InstrumentError', 'message': str(e)[:200]}
except Exception as e:
    result = {'op': 'result', 'kind': 'other', 'message': type(e).__name__}
_out.write(json.dumps(result) + chr(10))
_out.flush()
"""


def drive(sim: Any, freq_hz: float, averages: int, timeout_s: float = 60.0) -> dict[str, Any]:
    """Run `driver.measure_power(session, freq_hz, averages)` in the container. Every write, read and query
    the driver makes is executed here, on `sim`, and answered over the pipe; what the driver prints that is
    not a request is ignored. Returns the driver's own result message (`kind`: value, InstrumentError or
    other). The simulator's state stays in this process, out of the driver's reach."""
    cmd = container_command(DRIVER % {"freq": float(freq_hz), "n": int(averages)}, interactive=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    assert proc.stdin is not None and proc.stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_pump, args=(proc.stdout, lines.put), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CallFailed(f"no result within {timeout_s} s")
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise CallFailed(f"no result within {timeout_s} s") from exc
            if line is None:
                return {"kind": "other", "message": "the driver exited without a result"}
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            op = message.get("op")
            if op == "result":
                return message
            if op not in ("write", "read", "query"):
                continue
            reply: dict[str, Any]
            try:
                if op == "write":
                    sim.write(str(message.get("cmd", "")))
                    reply = {"value": None}
                elif op == "read":
                    reply = {"value": sim.read()}
                else:
                    reply = {"value": sim.query(str(message.get("cmd", "")))}
            except Exception as exc:  # a timeout of the simulated meter, raised in the driver
                reply = {"error": type(exc).__name__}
            proc.stdin.write(json.dumps(reply) + "\n")
            proc.stdin.flush()
    finally:
        _kill(cmd)
        proc.kill()


def _pump(stream: Any, put: Callable[[str | None], None]) -> None:
    for line in stream:
        put(line)
    put(None)


def strict_equal(actual: Any, expected: Any, tol: float = 0.0) -> bool:
    """Equal by type and value: `True` is not `1`, `1` is not `1.0`. Floats within `tol` (absolute)."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, float):
        return bool(abs(actual - expected) <= tol)
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(strict_equal(actual[k], expected[k], tol) for k in expected)
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return False
        return all(strict_equal(a, e, tol) for a, e in zip(actual, expected, strict=True))
    return bool(actual == expected)
