"""STORY-004 T1: what the harness needs to run a benchmark (S4-02, S4-03, the path half of S4-12).

- Prices: every S4-02 row, read from the cases file.
- Latency: each call's time is measured where it is made, kept on the call, and an attempt's latency is
  the sum of its calls, live and replayed alike; a retried call leaves its failed tries as calls too.
- Paths: with a workspace base, the gate and the tools resolve one relative path, refuse absolute paths
  and `..`, and read a recording made with Windows separators the same way on any OS.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest
import yaml

from harness.catalog import Catalog, tool
from harness.gate import Gate
from harness.ledger import Ledger
from harness.loop import Agent
from harness.prompts import PromptRegistry
from harness.providers import AnthropicProvider, RetryingProvider
from harness.replay import RecordingProvider, ReplayProvider
from harness.storage import read_jsonl
from harness.usage import call_cost

ROOT = Path(__file__).resolve().parents[2]
CASES = {c["id"]: c for c in yaml.safe_load((ROOT / "stories" / "STORY-004.cases.yaml").read_text("utf-8"))}


# ── S4-02: cost from measured usage per price component, null when the table does not cover it ──────


def _raw_usage(row: dict) -> dict:
    u = row["usage"]
    raw = {
        "input_tokens": u.get("input", 0),
        "output_tokens": u.get("output", 0),
        "cache_read_input_tokens": u.get("cache_read", 0),
        "inference_geo": u["inference_geo"],
    }
    if "cache_write_5m" in u:
        raw["cache_creation_input_tokens"] = u["cache_write_5m"]
        raw["cache_creation"] = {"ephemeral_5m_input_tokens": u["cache_write_5m"], "ephemeral_1h_input_tokens": 0}
    if "cache_creation_input_tokens" in u:  # `cache_split: absent`: the total without its 5m/1h split
        raw["cache_creation_input_tokens"] = u["cache_creation_input_tokens"]
    return raw


@pytest.mark.parametrize("row", [r for r in CASES["S4-02"]["rows"] if "usage" in r])
def test_s4_02_cost_per_price_component_or_null(row):
    cost = call_cost(_raw_usage(row), row["usage"]["model"])
    expected = row["expected"]["cost_usd"]
    if expected is None:
        assert cost is None
    else:
        assert cost == pytest.approx(expected, abs=1e-9)


# ── S4-03: latency per call, summed per attempt; retries are their own calls ─────────────────────────


class FakeMessage:
    # Like anthropic 1.12.1's streamed snapshot: the final message carries no `_request_id`; the id lives
    # on the stream (review finding 3B F5: the first version of this fake set it on the message).
    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self, mode: str = "json") -> dict:
        return dict(self._data)


class FakeStream:
    request_id = "req_1"

    def __init__(self, clock: list[float], message: FakeMessage, first_token_after: float, total: float) -> None:
        self.clock, self.message = clock, message
        self.first, self.total = first_token_after, total

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self):
        self.clock[0] += self.first
        yield SimpleNamespace(type="content_block_delta")
        self.clock[0] += self.total - self.first
        yield SimpleNamespace(type="message_stop")

    def get_final_message(self) -> FakeMessage:
        return self.message


class FakeClient:
    def __init__(self, clock: list[float]) -> None:
        self.clock = clock
        self.messages = SimpleNamespace(stream=self._stream, create=self._create)
        self.streamed: list[dict] = []

    def _stream(self, **request):
        self.streamed.append(request)
        msg = FakeMessage({"stop_reason": "end_turn", "content": [], "usage": {"input_tokens": 1}})
        return FakeStream(self.clock, msg, first_token_after=0.2, total=1.25)

    def _create(self, **request):  # pragma: no cover - the benchmark provider never calls it
        raise AssertionError("the benchmark provider streams")


def test_s4_03_streaming_provider_records_latency_ttft_and_request_id():
    clock = [100.0]
    provider = AnthropicProvider(FakeClient(clock), stream=True, clock=lambda: clock[0])
    response = provider.create(model="m", max_tokens=10, messages=[])
    assert response["_call"] == {"latency_s": 1.25, "ttft_s": 0.2, "request_id": "req_1", "failed_tries": []}
    assert response["stop_reason"] == "end_turn"


class Overloaded(Exception):
    status_code = 529


class FlakyProvider:
    """Fails the first call once with a retryable status, then answers from a script."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses, self.failed = list(responses), False

    def create(self, **request):
        if not self.failed:
            self.failed = True
            raise Overloaded("overloaded")
        return self.responses.pop(0)


def _answer(stop: str, latency: float, content=None) -> dict:
    return {
        "stop_reason": stop,
        "content": content or [{"type": "text", "text": "done"}],
        "usage": {"input_tokens": 10, "output_tokens": 2, "inference_geo": "global"},
        "_call": {"latency_s": latency, "ttft_s": None, "request_id": f"r{latency}", "failed_tries": []},
    }


def _tool_call(latency: float) -> dict:
    return _answer("tool_use", latency, [{"type": "tool_use", "id": "t1", "name": "read_value", "input": {"key": "a"}}])


@pytest.fixture
def agent_parts(tmp_path):
    catalog = Catalog()

    @tool(catalog, effect="read", description="Read a value", path_args=())
    def read_value(key: str) -> str:
        return key

    registry = PromptRegistry(tmp_path / "approvals.jsonl")
    registry.approve("sys", "be careful", by="reviewer", validation_ref="tests")
    return catalog, registry, Ledger(tmp_path / "ledger.jsonl"), tmp_path


def _agent(parts, provider, **kw):
    catalog, registry, ledger, tmp = parts
    return Agent(
        provider=provider, model="claude-sonnet-5-5", system="be careful", prompt_id="sys",
        registry=registry, catalog=catalog, gate=Gate(write_roots=[tmp]), ledger=ledger, **kw,
    )  # fmt: skip


def test_s4_03_attempt_latency_is_the_sum_of_recorded_call_latencies(agent_parts, tmp_path):
    case = CASES["S4-03"]
    lat = [c["latency_s"] for c in case["recording"]["calls"]]
    expected = case["rows"][0]["expected"]
    cassette = tmp_path / "attempt.jsonl"
    live = RecordingProvider(_Scripted([_tool_call(lat[0]), _answer("end_turn", lat[1])]), cassette)
    first = _agent(agent_parts, live).run("go")
    replayed = _agent(agent_parts, ReplayProvider(cassette)).run("go")
    for result in (first, replayed):
        assert [c["latency_s"] for c in result.calls] == expected["calls_latency_s"]
        assert result.latency_s == pytest.approx(expected["attempt_latency_s"])
    end = [r for r in read_jsonl(tmp_path / "ledger.jsonl") if r["kind"] == "run_end"][-1]
    assert end["latency_s"] == pytest.approx(expected["attempt_latency_s"])
    assert "wall_s" in end


def test_s4_03_a_retried_call_leaves_its_failed_try_as_a_call(agent_parts):
    expected = CASES["S4-03"]["rows"][1]["expected"]
    provider = RetryingProvider(
        FlakyProvider([_tool_call(1.25), _answer("end_turn", 0.75)]), retries=2, sleep=lambda s: None
    )
    result = _agent(agent_parts, provider).run("go")
    assert len(result.calls) == expected["calls"]
    assert sum(1 for c in result.calls if c.get("error")) == expected["retries_recorded"]
    calls = [r for r in read_jsonl(agent_parts[3] / "ledger.jsonl") if r["kind"] == "model_call"]
    assert len(calls) == expected["calls"]


def test_a_non_retryable_error_is_not_retried():
    class BadRequest(Exception):
        status_code = 400

    class Always:
        def __init__(self) -> None:
            self.n = 0

        def create(self, **request):
            self.n += 1
            raise BadRequest("bad")

    inner = Always()
    with pytest.raises(BadRequest):
        RetryingProvider(inner, retries=2, sleep=lambda s: None).create(model="m")
    assert inner.n == 1


class _Scripted:
    def __init__(self, responses: list[dict]) -> None:
        self.responses, self.requests = list(responses), []

    def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_effort_and_cache_are_sent_on_every_call_and_cache_is_off_by_default(agent_parts):
    on = _Scripted([_tool_call(0.1), _answer("end_turn", 0.1)])
    _agent(agent_parts, on, effort="high", cache=True).run("go")
    assert all(r["output_config"]["effort"] == "high" for r in on.requests)
    assert all(r["cache_control"] == {"type": "ephemeral"} for r in on.requests)
    off = _Scripted([_answer("end_turn", 0.1)])
    _agent(agent_parts, off).run("go")
    assert "cache_control" not in off.requests[0] and "output_config" not in off.requests[0]


def test_a_call_without_measured_latency_falls_back_to_the_wall_clock(agent_parts):
    # Recordings made before latency was kept (STORY-002) still replay; their latency is the wall clock.
    plain = _Scripted([{"stop_reason": "end_turn", "content": [], "usage": {"input_tokens": 1}}])
    result = _agent(agent_parts, plain).run("go")
    assert result.latency_s == result.wall_s


# ── S4-12 (paths): relative to the workspace, one resolver for gate and tools ───────────────────────


@pytest.fixture
def workspace(tmp_path):
    w = tmp_path / "w"
    (w / "sub").mkdir(parents=True)
    (w / "driver.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("s\n", encoding="utf-8")
    return w


def _read_tool():
    catalog = Catalog()

    @tool(catalog, effect="read", description="read", path_args=("path",))
    def read(path: str) -> str:  # pragma: no cover - only the gate is exercised
        return path

    return catalog.get("read")


@pytest.mark.parametrize(
    ("raw", "verdict"),
    [
        ("driver.py", "allow"),
        ("sub/new.py", "allow"),
        ("sub\\new.py", "allow"),  # a Windows-made recording replays on Linux
        ("../secret.txt", "deny"),
        ("sub/../driver.py", "deny"),  # `..` is refused outright, not normalised away
        ("/etc/hosts", "deny"),
        ("C:/Windows/win.ini", "deny"),
        ("", "deny"),
    ],
)
def test_s4_12_gate_resolves_paths_relative_to_the_workspace(workspace, raw, verdict):
    gate = Gate(read_roots=["."], write_roots=["."], base=workspace)
    assert gate.decide(_read_tool(), {"path": raw}).verdict == verdict


def test_s4_12_backslash_dotdot_is_refused_like_slash_dotdot(workspace):
    gate = Gate(read_roots=["."], base=workspace)
    assert gate.decide(_read_tool(), {"path": "sub\\..\\driver.py"}).verdict == "deny"


def test_s4_12_an_absolute_path_is_refused_even_inside_the_workspace(workspace):
    # Relative only, so a recording never carries a machine's temporary directory.
    raw = (workspace / "driver.py").resolve().as_posix()
    raw = raw[2:] if PureWindowsPath(raw).drive else raw  # rooted, without a drive letter
    gate = Gate(read_roots=["."], base=workspace)
    assert gate.decide(_read_tool(), {"path": raw}).verdict == "deny"


def test_s4_12_the_tool_and_the_gate_resolve_the_same_path(workspace):
    gate = Gate(read_roots=["."], base=workspace)
    assert gate.resolve("sub\\new.py") == (workspace / "sub" / "new.py").resolve()
    assert gate.resolve("../secret.txt") is None


def test_a_retry_waits_at_least_what_the_server_asks_for():
    # A 529 or 429 can carry retry-after; the wait honours it (capped), never just the fixed backoff.
    class Response:
        headers = {"retry-after": "30"}

    class Overloaded529(Exception):
        status_code = 529
        response = Response()

    class Once:
        def __init__(self) -> None:
            self.n = 0

        def create(self, **request):
            self.n += 1
            if self.n == 1:
                raise Overloaded529("overloaded")
            return {"content": [], "usage": {}, "_call": {}}

    waits: list[float] = []
    RetryingProvider(Once(), retries=2, backoff_s=2.0, sleep=waits.append).create(model="m")
    assert waits == [30.0]
    waits.clear()
    Response.headers = {"retry-after": "9999"}
    RetryingProvider(Once(), retries=2, backoff_s=2.0, sleep=waits.append, max_wait_s=120.0).create(model="m")
    assert waits == [120.0]
