"""One SBOM component, the same shape whatever format it came from."""
from __future__ import annotations

from dataclasses import dataclass


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
