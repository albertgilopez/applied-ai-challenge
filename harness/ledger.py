"""Append-only JSONL ledger. History, never state.

A correction is a new line that points at the line it corrects; nothing is ever
rewritten. If the ledger cannot be written the caller gets the exception: for an
audit trail, an unrecorded decision is worse than a failed one.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Ledger:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict) -> str:
        row = {
            "id": uuid.uuid4().hex[:12],
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            **event,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row["id"]

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
