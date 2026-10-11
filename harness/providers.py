"""Live provider: the Anthropic Messages API, returning plain dicts so that
responses can be recorded and replayed byte for byte.

A benchmark needs two things from a call besides its answer, measured where the call is made
(STORY-004 DR-4): how long it took (and, streaming, when the first token came) and the provider's
request id. They travel with the response under `_call`, which is response data, never request
data, so recording keys do not change. Retries are made here, by `RetryingProvider`, never by the
SDK: each failed try is kept on the response so the loop can record it as a call of its own.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from harness.storage import JSONObject

# Statuses a later try can fix: rate limit, server errors, and the provider's "overloaded" (529).
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})


class Provider(Protocol):
    def create(self, **request: Any) -> JSONObject: ...


class AnthropicProvider:
    def __init__(
        self,
        client: Any = None,
        *,
        stream: bool = False,
        max_retries: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client is None:
            from anthropic import Anthropic

            # `max_retries=0` hands retries to RetryingProvider, where each try is recorded.
            client = Anthropic() if max_retries is None else Anthropic(max_retries=max_retries)
        self.client, self.stream, self.clock = client, stream, clock

    def create(self, **request: Any) -> JSONObject:
        started = self.clock()
        ttft: float | None = None
        if self.stream:
            # Streaming is required for large `max_tokens`: the SDK refuses a non-streaming call above
            # about 21k output tokens, and thinking at high effort counts toward that budget.
            with self.client.messages.stream(**request) as events:
                for event in events:
                    if ttft is None and getattr(event, "type", "") == "content_block_delta":
                        ttft = self.clock() - started
                message = events.get_final_message()
        else:
            message = self.client.messages.create(**request)
        latency = self.clock() - started
        # Read before model_dump: the request id is set on the parsed object and dropped by the dump.
        request_id = getattr(message, "_request_id", None)
        response: JSONObject = message.model_dump(mode="json")
        response["_call"] = {
            "latency_s": round(latency, 3),
            "ttft_s": None if ttft is None else round(ttft, 3),
            "request_id": request_id,
            "failed_tries": [],
        }
        return response


def _retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS
    try:
        from anthropic import APIConnectionError
    except ImportError:  # pragma: no cover - the SDK is a dependency
        return False
    return isinstance(exc, APIConnectionError)  # covers timeouts too


class RetryingProvider:
    """Retries a retryable failure up to `retries` times with exponential backoff. Every failed try is
    kept on the final response (`_call.failed_tries`) with its error and how long it took, so a retry
    is never invisible in the ledger or in the latency."""

    def __init__(
        self,
        inner: Provider,
        *,
        retries: int = 2,
        backoff_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inner, self.retries, self.backoff_s = inner, retries, backoff_s
        self.sleep, self.clock = sleep, clock

    def create(self, **request: Any) -> JSONObject:
        failed: list[JSONObject] = []
        for attempt in range(self.retries + 1):
            started = self.clock()
            try:
                response = self.inner.create(**request)
            except Exception as exc:
                if attempt == self.retries or not _retryable(exc):
                    raise
                failed.append(
                    {
                        "latency_s": round(self.clock() - started, 3),
                        "error": f"{type(exc).__name__}: {getattr(exc, 'status_code', '')}".rstrip(": "),
                    }
                )
                self.sleep(self.backoff_s * (2**attempt))
                continue
            call = dict(response.get("_call") or {})
            call["failed_tries"] = [*call.get("failed_tries", []), *failed]
            return {**response, "_call": call}
        raise AssertionError("unreachable")  # pragma: no cover
