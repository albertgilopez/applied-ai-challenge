"""Live provider: the Anthropic Messages API, returning plain dicts so that
responses can be recorded and replayed byte for byte."""
from __future__ import annotations


class AnthropicProvider:
    def __init__(self, client=None) -> None:
        if client is None:
            from anthropic import Anthropic
            client = Anthropic()
        self.client = client

    def create(self, **request) -> dict:
        return self.client.messages.create(**request).model_dump(mode="json")
