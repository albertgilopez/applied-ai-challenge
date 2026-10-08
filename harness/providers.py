"""Live provider: the Anthropic Messages API, returning plain dicts so that
responses can be recorded and replayed byte for byte."""

from __future__ import annotations

from typing import Any, Protocol

from harness.storage import JSONObject


class Provider(Protocol):
    def create(self, **request: Any) -> JSONObject: ...


class AnthropicProvider:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self.client = client

    def create(self, **request: Any) -> JSONObject:
        response: JSONObject = self.client.messages.create(**request).model_dump(mode="json")
        return response
