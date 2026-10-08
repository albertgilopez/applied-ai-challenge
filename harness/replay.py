"""Record and replay model calls: the lab.

`RecordingProvider` wraps a live provider and stores every response under a
hash of its request. `ReplayProvider` answers from that file and raises on a
request it never saw, so CI runs without network or an API key, and a recorded
corpus doubles as a regression eval: if the code sends a different request, the
replay fails loudly instead of quietly calling the model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class CassetteMiss(KeyError):
    pass


def request_key(request: dict) -> str:
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class RecordingProvider:
    def __init__(self, inner, cassette: Path | str) -> None:
        self.inner = inner
        self.cassette = Path(cassette)

    def create(self, **request) -> dict:
        response = self.inner.create(**request)
        data = _load(self.cassette)
        data[request_key(request)] = response
        self.cassette.parent.mkdir(parents=True, exist_ok=True)
        self.cassette.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return response


class ReplayProvider:
    def __init__(self, cassette: Path | str) -> None:
        self.data = _load(Path(cassette))

    def create(self, **request) -> dict:
        key = request_key(request)
        if key not in self.data:
            raise CassetteMiss(f"no recorded response for request {key[:12]}; re-record with a live provider")
        return self.data[key]
