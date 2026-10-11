"""STORY-004: other providers' models in configuration B, through OpenRouter's OpenAI-compatible API.

The adapter takes the same request the agent loop builds for the Anthropic API and returns the response
in the same shape, so the loop, the recordings, the budget and the replay are unchanged. Nothing here
calls the network: the HTTP POST is scripted.
"""

from __future__ import annotations

import json

import pytest

from harness.openrouter import OpenRouterError, OpenRouterProvider, from_chat, to_chat
from harness.providers import RetryingProvider
from harness.usage import call_cost

TOOLS = [{"name": "read_file", "description": "Read a file.", "input_schema": {"type": "object", "properties": {}}}]


def request(messages, **kw):
    return {
        "model": "openai/gpt-5.6-sol",
        "max_tokens": 32000,
        "system": [{"type": "text", "text": "You are an engineer."}],
        "messages": messages,
        "tools": TOOLS,
        "output_config": {"effort": "high"},
        "cache_control": {"type": "ephemeral"},
        **kw,
    }


def test_the_request_is_translated_to_chat_completions():
    msgs = [
        {"role": "user", "content": "Fix add."},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Reading."},
            {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "mod.py"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "def add(a, b): ...", "is_error": False},
        ]},
    ]  # fmt: skip
    body = to_chat(request(msgs))
    assert body["model"] == "openai/gpt-5.6-sol" and body["max_tokens"] == 32000
    assert body["messages"][0] == {"role": "system", "content": "You are an engineer."}
    assert body["messages"][1] == {"role": "user", "content": "Fix add."}
    assistant = body["messages"][2]
    assert assistant["content"] == "Reading."
    assert assistant["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "mod.py"}'}}
    ]
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "def add(a, b): ..."}
    assert body["tools"] == [
        {"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                          "parameters": {"type": "object", "properties": {}}}}
    ]  # fmt: skip
    assert body["reasoning"] == {"effort": "high"} and body["usage"] == {"include": True}
    assert "cache_control" not in body and "output_config" not in body


CHAT = {
    "id": "gen-123",
    "choices": [{
        "finish_reason": "tool_calls",
        "message": {"role": "assistant", "content": "Writing.", "tool_calls": [
            {"id": "call_9", "type": "function", "function": {"name": "write_file", "arguments": '{"path": "mod.py"}'}},
        ]},
    }],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "prompt_tokens_details": {"cached_tokens": 200},
              "completion_tokens_details": {"reasoning_tokens": 100}, "cost": 0.00498},
}  # fmt: skip


def test_the_response_comes_back_in_the_anthropic_shape_with_its_usage():
    r = from_chat(CHAT)
    assert r["stop_reason"] == "tool_use"
    assert r["content"] == [
        {"type": "text", "text": "Writing."},
        {"type": "tool_use", "id": "call_9", "name": "write_file", "input": {"path": "mod.py"}},
    ]
    u = r["usage"]
    assert (u["input_tokens"], u["cache_read_input_tokens"], u["output_tokens"]) == (1000, 200, 300)
    assert u["output_tokens_details"]["thinking_tokens"] == 100 and u["inference_geo"] == "global"
    assert u["provider_cost_usd"] == 0.00498


def test_our_price_table_matches_what_the_provider_charged():
    # GPT-5.6 Sol at 2 / 10 per MTok, cache read 0.2: 1000 x 2 + 200 x 0.2 + 300 x 10 = 5040 -> 0.00504 USD.
    # The provider's own figure is kept beside ours on every call, so a drift in the table is visible.
    assert call_cost(from_chat(CHAT)["usage"], "openai/gpt-5.6-sol") == pytest.approx(0.00504)


@pytest.mark.parametrize(
    ("finish", "stop"), [("stop", "end_turn"), ("length", "max_tokens"), ("content_filter", "refusal")]
)
def test_finish_reasons_map_to_the_outcomes_the_runner_names(finish, stop):
    body = {"id": "g", "choices": [{"finish_reason": finish, "message": {"content": "x"}}], "usage": {}}
    assert from_chat(body)["stop_reason"] == stop


def test_unparseable_tool_arguments_reach_the_tool_as_an_error_not_a_crash():
    body = json.loads(json.dumps(CHAT))
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    [_, use] = from_chat(body)["content"]
    assert use["input"] == {"_unparsed_arguments": "{not json"}


class Scripted:
    def __init__(self, *answers):
        self.answers, self.sent = list(answers), []

    def __call__(self, url, body, headers, timeout):
        self.sent.append((url, json.loads(body), headers))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_the_provider_posts_with_the_key_and_records_the_call():
    post = Scripted(CHAT)
    r = OpenRouterProvider(api_key="sk-or-test", post=post).create(**request([{"role": "user", "content": "go"}]))
    url, body, headers = post.sent[0]
    assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer sk-or-test"
    assert body["model"] == "openai/gpt-5.6-sol"
    assert r["_call"]["request_id"] == "gen-123" and r["_call"]["latency_s"] >= 0


def test_an_error_in_a_200_body_is_an_error_and_a_429_is_retried():
    post = Scripted({"error": {"code": 429, "message": "rate limited"}}, CHAT)
    provider = RetryingProvider(OpenRouterProvider(api_key="k", post=post), retries=2, sleep=lambda s: None)
    r = provider.create(**request([{"role": "user", "content": "go"}]))
    assert r["stop_reason"] == "tool_use" and len(r["_call"]["failed_tries"]) == 1


def test_a_400_is_not_retried():
    post = Scripted({"error": {"code": 400, "message": "bad"}})
    with pytest.raises(OpenRouterError):
        RetryingProvider(OpenRouterProvider(api_key="k", post=post), retries=2, sleep=lambda s: None).create(
            **request([{"role": "user", "content": "go"}])
        )
