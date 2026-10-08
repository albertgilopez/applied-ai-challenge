"""The license policy: which SPDX ids are allowed, need review, or are rejected.

Lookup is case-insensitive (SPDX ids are), exact otherwise: an id the policy
does not list returns `None` and the caller treats it as `Needs review`
(STORY-001 DR-1). A policy that contradicts itself, or carries something that
is not a license id, is refused when it is loaded rather than when it misfires.
"""
from __future__ import annotations

from dataclasses import dataclass

SECTIONS = {"allowed": "Allow", "review": "Needs review", "rejected": "Reject"}


class PolicyError(ValueError):
    pass


def _key(text: str) -> str:
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class Policy:
    verdicts: dict[str, str]

    @classmethod
    def from_dict(cls, data: dict) -> "Policy":
        if not isinstance(data, dict) or not any(data.get(s) for s in SECTIONS):
            raise PolicyError("the policy is empty: it needs at least one of " + ", ".join(SECTIONS))
        unknown = sorted(set(data) - set(SECTIONS))
        if unknown:
            raise PolicyError(f"unknown section(s) {unknown}; expected {list(SECTIONS)}")
        verdicts: dict[str, str] = {}
        where: dict[str, str] = {}
        for section, verdict in SECTIONS.items():
            for entry in data.get(section) or []:
                if not isinstance(entry, str) or not entry.strip():
                    raise PolicyError(f"{section}: {entry!r} is not a license id (quote it if it is)")
                k = _key(entry)
                if k in where and where[k] != section:
                    raise PolicyError(f"{entry!r} is listed in both {where[k]} and {section}")
                verdicts[k], where[k] = verdict, section
        return cls(verdicts)

    def lookup(self, license_text: str) -> str | None:
        return self.verdicts.get(_key(license_text))
