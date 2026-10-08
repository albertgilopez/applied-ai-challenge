"""The license policy: which SPDX ids are allowed, need review, or are rejected.

Lookup is case-insensitive (SPDX ids are), exact otherwise: an id the policy
does not list returns `None` and the caller treats it as `Needs review`
(STORY-001 DR-1). A policy that contradicts itself, or carries something that
is not a license id, is refused when it is loaded rather than when it misfires.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from core.component import JSONObject

ALLOW, REVIEW, REJECT = "Allow", "Needs review", "Reject"
SECTIONS = {"allowed": ALLOW, "review": REVIEW, "rejected": REJECT}


class PolicyError(ValueError):
    pass


def _key(text: str) -> str | None:
    """Normalised lookup key, or None for text that cannot be an SPDX id.

    SPDX ids are case-insensitive in ASCII only. Full Unicode case folding (`casefold()`) turned
    lookalikes such as `BSD-3-Clau\\u017fe` (long s) into an allowed id; non-ASCII text now never
    matches, so it stays `Needs review` (STORY-001 DR-2, security scan C9).
    """
    if not text.isascii():
        return None
    return " ".join(text.split()).lower()


@dataclass(frozen=True)
class Policy:
    verdicts: dict[str, str]

    @classmethod
    def from_dict(cls, data: JSONObject) -> Policy:
        if not isinstance(data, dict) or not any(data.get(s) for s in SECTIONS):
            raise PolicyError("the policy is empty: it needs at least one of " + ", ".join(SECTIONS))
        unknown = sorted(str(k) for k in set(data) - set(SECTIONS))  # str(): YAML keys may be bools
        if unknown:
            raise PolicyError(f"unknown section(s) {unknown}; expected {list(SECTIONS)}")
        where: dict[str, str] = {}  # normalised id -> the section that lists it
        for section in SECTIONS:
            entries = data.get(section)
            if entries is None:
                continue
            # A scalar would be iterated character by character (`rejected: GPL-3.0-only` became
            # {g, p, l, ...}) and the rejection would silently vanish (security scan C8).
            if not isinstance(entries, list):
                raise PolicyError(f"{section} must be a list of license ids, got {type(entries).__name__}")
            for i, entry in enumerate(entries):
                # Report the type and position, never the entry itself: echoing a YAML alias bomb
                # made the error message exponential (security scan C6).
                if not isinstance(entry, str) or not entry.strip():
                    raise PolicyError(
                        f"{section}[{i}]: a {type(entry).__name__} is not a license id (quote it if it is)"
                    )
                k = _key(entry)
                if k is None:
                    raise PolicyError(f"{section}[{i}]: license ids are ASCII")
                if k in where and where[k] != section:
                    raise PolicyError(f"{entry!r} is listed in both {where[k]} and {section}")
                where[k] = section
        return cls({k: SECTIONS[s] for k, s in where.items()})

    def digest(self) -> str:
        """sha256 of the policy as loaded: normalised ids and their verdicts, sorted.

        A recorded decision is reused only under the same digest (STORY-003 DR-4). Hashing what was
        loaded, not the file, means a comment or a reordered list does not reopen every item, while
        moving an id to another section does.
        """
        canonical = json.dumps(sorted(self.verdicts.items()), separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def lookup(self, license_text: str) -> str | None:
        k = _key(license_text)
        return None if k is None else self.verdicts.get(k)
