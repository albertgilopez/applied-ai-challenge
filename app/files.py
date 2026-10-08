"""Read SBOM and policy files into the pure core.

This is the only place that touches the filesystem and YAML; `core/` receives
plain dicts. Both readers cap the input size before parsing anything, and turn
every parser failure into the core's own error types, so a bad file stops the
run with a message instead of producing an empty review.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from core.component import Component
from core.policy import Policy, PolicyError
from core.sbom import FormatError, SbomDocument, read_sbom

MAX_SBOM_BYTES = 20 * 1024 * 1024
MAX_POLICY_BYTES = 256 * 1024


def _read_bytes(path: Path | str, limit: int, error: type[Exception]) -> bytes:
    path = Path(path)
    size = path.stat().st_size
    if size > limit:
        raise error(f"{path.name} is {size} bytes, above the {limit}-byte limit")
    return path.read_bytes()


def _read(path: Path | str, limit: int, error: type[Exception]) -> str:
    return _read_bytes(path, limit, error).decode("utf-8")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """`json.loads` keeps the LAST of two equal keys; another tool, or a person reading the file,
    may read the first. Two answers for one component is a malformed SBOM (DR-8, scan C11)."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise FormatError(f"duplicate key {key!r} in a JSON object")
        out[key] = value
    return out


def load_sbom(path: Path | str) -> list[Component]:
    return load_sbom_document(path)[0].components


def load_sbom_document(path: Path | str) -> tuple[SbomDocument, str]:
    """The parsed SBOM (components and product) and the sha256 of the exact bytes that were read."""
    raw = _read_bytes(path, MAX_SBOM_BYTES, FormatError)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FormatError(f"{Path(path).name} is not UTF-8") from exc
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise FormatError(f"{Path(path).name} is not valid JSON: {exc.msg} at line {exc.lineno}") from exc
    except RecursionError as exc:
        raise FormatError(f"{Path(path).name} is nested too deeply") from exc
    return read_sbom(doc), hashlib.sha256(raw).hexdigest()


def load_policy(path: Path | str) -> Policy:
    text = _read(path, MAX_POLICY_BYTES, PolicyError)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicyError(f"{Path(path).name} is not valid YAML: {exc}") from exc
    except RecursionError as exc:  # PyYAML raises it, not a YAMLError, on deep nesting (scan C16)
        raise PolicyError(f"{Path(path).name} is nested too deeply") from exc
    return Policy.from_dict(data or {})
