"""The one way this repo writes its records: JSON Lines, LF endings, UTC timestamps.

Every durable record (decision ledger, prompt approvals, recorded model calls)
is appended one line at a time, so a crash loses at most the line being
written and history is never rewritten. Files are opened with `newline="\n"`
so the bytes are identical on Windows and Linux; text mode would otherwise
write CRLF on Windows, and `.gitattributes` only normalises files that pass
through git.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# One record, a tool call or an API payload: a JSON object with string keys.
JSONObject = dict[str, Any]


def utc_stamp() -> str:
    """Seconds-resolution UTC timestamp, e.g. 2026-10-08T19:30:00Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_jsonl(path: Path | str, record: JSONObject) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path | str) -> Iterator[JSONObject]:
    path = Path(path)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
