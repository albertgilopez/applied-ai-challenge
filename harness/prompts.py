"""The system prompt is a governed artifact.

It is approved by content hash, together with who approved it and the evidence
(an eval run, a review) that justified it. Changing one character changes the
hash, so an edited prompt is an unapproved prompt. In `prod` the agent refuses
to start on an unapproved prompt; elsewhere it runs and says so in the ledger.

Approvals are appended as JSON lines, like every other record: the approval
history can grow but never be edited, and "is this approved?" is derived from it.
Line endings are normalised before hashing, so a prompt read from a CRLF file on
Windows keeps the approval it was given on Linux.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from harness.storage import append_jsonl, read_jsonl, utc_stamp

RELAXED_ENVS = frozenset({"dev", "test"})  # the only envs that may run an unapproved prompt


class UnapprovedPrompt(RuntimeError):
    pass


def digest(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


class PromptRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def approve(self, prompt_id: str, text: str, *, by: str, validation_ref: str) -> str:
        if not by.strip() or not validation_ref.strip():
            raise ValueError("an approval needs who approved it and the evidence it rests on")
        h = digest(text)
        append_jsonl(
            self.path,
            {"prompt_id": prompt_id, "sha256": h, "by": by, "validation_ref": validation_ref, "at": utc_stamp()},
        )
        return h

    def is_approved(self, prompt_id: str, text: str) -> bool:
        h = digest(text)
        return any(r["prompt_id"] == prompt_id and r["sha256"] == h for r in read_jsonl(self.path))

    def require(self, prompt_id: str, text: str, env: str) -> bool:
        """Return whether the prompt is approved; raise unless the env is an explicit dev or test.

        Fail closed: "production", "PROD", " prod", "" or a typo are all prod. The old check was
        `env == "prod"`, so any other spelling ran an unapproved prompt (security scan H3).
        """
        ok = self.is_approved(prompt_id, text)
        if not ok and env.strip().lower() not in RELAXED_ENVS:
            raise UnapprovedPrompt(f"prompt {prompt_id!r} ({digest(text)[:12]}) has no approval")
        return ok
