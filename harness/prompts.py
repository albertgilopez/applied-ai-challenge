"""The system prompt is a governed artifact.

It is approved by content hash, together with who approved it and the evidence
(an eval run, a review) that justified it. Changing one character changes the
hash, so an edited prompt is an unapproved prompt. In `prod` the agent refuses
to start on an unapproved prompt; elsewhere it runs and says so in the ledger.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class UnapprovedPrompt(RuntimeError):
    pass


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PromptRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def approve(self, prompt_id: str, text: str, *, by: str, validation_ref: str) -> str:
        if not by.strip() or not validation_ref.strip():
            raise ValueError("an approval needs who approved it and the evidence it rests on")
        data = self._load()
        entry = {
            "sha256": digest(text),
            "by": by,
            "validation_ref": validation_ref,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        data.setdefault(prompt_id, []).append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return entry["sha256"]

    def is_approved(self, prompt_id: str, text: str) -> bool:
        h = digest(text)
        return any(e["sha256"] == h for e in self._load().get(prompt_id, []))

    def require(self, prompt_id: str, text: str, env: str) -> bool:
        """Return whether the prompt is approved; raise in prod if it is not."""
        ok = self.is_approved(prompt_id, text)
        if not ok and env == "prod":
            raise UnapprovedPrompt(f"prompt {prompt_id!r} ({digest(text)[:12]}) has no approval")
        return ok
