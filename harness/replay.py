"""Record and replay model calls: the lab.

`RecordingProvider` wraps a live provider and appends every response, keyed by
a hash of its request, as one JSON line. `ReplayProvider` answers from that
file and raises on a request it never saw, so CI runs without network or an API
key, and a recorded corpus doubles as a regression eval: if the code sends a
different request, the replay fails loudly instead of quietly calling the model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness.storage import append_jsonl, read_jsonl


class CassetteMiss(KeyError):
    pass


def request_key(request: dict) -> str:
    # No `default=str`: a request that is not plain JSON should fail here, not be
    # silently stringified into a key nobody can reproduce.
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecordingProvider:
    def __init__(self, inner, cassette: Path | str) -> None:
        self.inner = inner
        self.cassette = Path(cassette)

    def create(self, **request) -> dict:
        response = self.inner.create(**request)
        append_jsonl(self.cassette, {"key": request_key(request), "response": response})
        return response


class ReplayProvider:
    def __init__(self, cassette: Path | str) -> None:
        # The last recording of a request wins, so re-recording appends instead of editing.
        self.data = {r["key"]: r["response"] for r in read_jsonl(cassette)}

    def create(self, **request) -> dict:
        key = request_key(request)
        if key not in self.data:
            raise CassetteMiss(f"no recorded response for request {key[:12]}; re-record with a live provider")
        return self.data[key]
