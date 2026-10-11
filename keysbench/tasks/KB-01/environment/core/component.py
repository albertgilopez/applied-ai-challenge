"""One SBOM component, the same shape whatever format it came from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A parsed JSON object as it comes from an SBOM or a policy: keys are strings,
# values are whatever the document holds. Narrowed by the code that reads it.
JSONObject = dict[str, Any]


@dataclass(frozen=True)
class Component:
    ref: str
    name: str
    version: str | None
    type: str
    purl: str | None
    license_expression: str | None
    source_url: str | None

    @property
    def is_ai_model(self) -> bool:
        """Derived, not stored: each parser maps its format's signal onto `type` (DR-6)."""
        return self.type == "machine-learning-model"

    @property
    def identity(self) -> str:
        """Stable key across formats: the purl when there is one, else name@version."""
        return self.purl or f"{self.name}@{self.version or ''}"
