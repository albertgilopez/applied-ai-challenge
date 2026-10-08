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
    is_ai_model: bool = False

    @property
    def identity(self) -> str:
        """Stable key across formats: the purl when there is one, else name@version."""
        return self.purl or f"{self.name}@{self.version or ''}"
