"""Other providers' models through OpenRouter's OpenAI-compatible chat completions API.

`OpenRouterProvider.create` takes the request the agent loop builds for the Anthropic Messages API and
returns the response in the same shape. The loop, the recordings, the budget and the replay therefore
work unchanged for any model: what differs between providers is translated here and nowhere else.

Translation, both ways:

- system blocks become one system message; a user turn of `tool_result` blocks becomes one `tool`
  message per result; an assistant turn's `tool_use` blocks become `tool_calls`, its text the content.
- tools become functions (`input_schema` is the JSON schema `parameters` expects).
- `output_config.effort` becomes OpenRouter's `reasoning.effort`; `cache_control` is dropped (caching
  is the provider's own, and what it saved comes back as cached prompt tokens).
- the usage comes back split like Anthropic's: uncached input, cache reads, output (reasoning tokens
  included, as Anthropic counts thinking). The provider's own cost is kept beside it
  (`provider_cost_usd`), so a drift between our price table and what was charged is visible per call.

The POST is a parameter so tests never touch the network. Errors carry `status_code`, so
`RetryingProvider` retries a 429 or a 5xx and not a 400, the same as for the Anthropic API. OpenRouter
also returns some errors inside a 200 body; those are raised the same way.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from harness.storage import JSONObject

BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_S = 900.0  # one call at 32k output tokens with reasoning can take minutes
FINISH = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}

Post = Callable[[str, bytes, dict[str, str], float], JSONObject]


class OpenRouterError(RuntimeError):
    def __init__(self, status_code: int, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(f"OpenRouter {status_code}: {message[:300]}")
        self.status_code = status_code
        self.response = type("Response", (), {"headers": headers or {}})()


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def to_chat(request: JSONObject) -> JSONObject:
    messages: list[JSONObject] = []
    system = _text(request.get("system"))
    if system:
        messages.append({"role": "system", "content": system})
    for m in request.get("messages") or []:
        content = m.get("content")
        if isinstance(content, str):
            messages.append({"role": m["role"], "content": content})
            continue
        blocks = content or []
        if m["role"] == "assistant":
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                }
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            msg: JSONObject = {"role": "assistant", "content": _text(blocks) or None}
            if calls:
                msg["tool_calls"] = calls
            messages.append(msg)
            continue
        for b in blocks:
            if b.get("type") == "tool_result":
                messages.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": _text(b.get("content"))})
        text = _text(blocks)
        if text:
            messages.append({"role": "user", "content": text})
    body: JSONObject = {
        "model": request["model"],
        "max_tokens": request.get("max_tokens"),
        "messages": messages,
        "usage": {"include": True},
    }
    if request.get("tools"):
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in request["tools"]
        ]
    effort = (request.get("output_config") or {}).get("effort")
    if effort:
        body["reasoning"] = {"effort": effort}
    return body


def from_chat(body: JSONObject) -> JSONObject:
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content: list[JSONObject] = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                args = {"_unparsed_arguments": raw}
        except json.JSONDecodeError:
            args = {"_unparsed_arguments": raw}  # the tool then fails, and the model sees why
        content.append({"type": "tool_use", "id": call.get("id"), "name": fn.get("name"), "input": args})
    u = body.get("usage") or {}
    prompt = int(u.get("prompt_tokens") or 0)
    details = u.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    # A prompt the provider caches is billed as a cache write, above the input price (GPT-5.6 Sol: 2.5
    # against 2.0 per MTok). Without this field our cost was 11 % under what was charged (live, 2026-10-11).
    written = int(details.get("cache_write_tokens") or 0)
    usage: JSONObject = {
        "input_tokens": prompt - cached - written,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": written,
        # One TTL tier per write, priced at the table's cache write; the split is what `call_cost` checks.
        "cache_creation": {"ephemeral_5m_input_tokens": written, "ephemeral_1h_input_tokens": 0},
        "output_tokens": int(u.get("completion_tokens") or 0),
        "output_tokens_details": {
            "thinking_tokens": int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        },
        "inference_geo": "global",  # OpenRouter does not price by region
        "provider_cost_usd": u.get("cost"),
    }
    return {
        "id": body.get("id"),
        "type": "message",
        "role": "assistant",
        "model": body.get("model"),
        "content": content,
        "stop_reason": FINISH.get(str(choice.get("finish_reason")), str(choice.get("finish_reason"))),
        "usage": usage,
    }


def _urllib_post(url: str, data: bytes, headers: dict[str, str], timeout: float) -> JSONObject:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https base URL
            parsed: JSONObject = json.loads(r.read().decode("utf-8"))
            return parsed
    except urllib.error.HTTPError as exc:
        raise OpenRouterError(exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenRouterError(503, f"connection: {exc}") from exc  # a network failure is retried like a 503


class OpenRouterProvider:
    def __init__(
        self,
        *,
        api_key: str,
        post: Post | None = None,
        base_url: str = BASE_URL,
        timeout_s: float = TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api_key, self.post, self.base_url = api_key, post or _urllib_post, base_url
        self.timeout_s, self.clock = timeout_s, clock

    def create(self, **request: Any) -> JSONObject:
        started = self.clock()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "KeysBench",
        }
        body = self.post(
            f"{self.base_url}/chat/completions", json.dumps(to_chat(request)).encode("utf-8"), headers, self.timeout_s
        )
        if body.get("error"):
            err = body["error"]
            raise OpenRouterError(int(err.get("code") or 500), str(err.get("message", "")))
        response = from_chat(body)
        response["_call"] = {
            "latency_s": round(self.clock() - started, 3),
            "ttft_s": None,
            "request_id": body.get("id"),
            "failed_tries": [],
        }
        return response
