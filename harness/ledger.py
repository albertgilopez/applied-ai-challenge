"""Append-only JSONL ledger. History, never state.

A correction is a new line that points at the line it corrects; nothing is ever
rewritten. If the ledger cannot be written the caller gets the exception: for an
audit trail, an unrecorded decision is worse than a failed one.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from harness.storage import append_jsonl, read_jsonl, utc_stamp


class Ledger:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, event: dict) -> str:
        row = {"id": uuid.uuid4().hex[:12], "at": utc_stamp(), **event}
        append_jsonl(self.path, row)
        return row["id"]

    def read(self) -> list[dict]:
        return list(read_jsonl(self.path))
