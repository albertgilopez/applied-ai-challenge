"""Reading a model card: by model id, from a local directory or one fixed host (DOCTRINE D-04).

The tool takes `org/name` and nothing else. It never takes a URL: a URL from the model, or from a
poisoned SBOM entry, could point the request anywhere. The host and the path are built here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

HOST = "https://huggingface.co"
MAX_CARD_BYTES = 256 * 1024
_PART = r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}"
_MODEL_ID = re.compile(rf"{_PART}/{_PART}")

Fetch = Callable[[str], str]


class InvalidModelId(ValueError):
    pass


class CardNotFound(LookupError):
    pass


def valid_model_id(model_id: object) -> bool:
    """A format check, so a pattern is the right tool: `org/name`, no `..`, nothing else."""
    return isinstance(model_id, str) and bool(_MODEL_ID.fullmatch(model_id)) and ".." not in model_id


def model_id_from_purl(purl: str | None) -> str | None:
    """`pkg:huggingface/<org>/<name>[@version][?qualifiers]` → `<org>/<name>`, or None."""
    prefix = "pkg:huggingface/"
    if not purl or not purl.startswith(prefix):
        return None
    candidate = purl[len(prefix) :].split("?")[0].split("#")[0].split("@")[0]
    return candidate if valid_model_id(candidate) else None


def card_path(model_id: str, cards_dir: Path) -> Path:
    org, name = model_id.split("/")
    return cards_dir / f"{org}__{name}.md"


def card_url(model_id: str) -> str:
    return f"{HOST}/{model_id}/raw/main/README.md"


def load_card(model_id: str, cards_dir: Path | str, fetch: Fetch | None = None) -> str:
    """The card text: the local copy if there is one; otherwise the fixed host, only when a fetcher
    is given (the CLI passes one with `--live`). Tests and CI never fetch."""
    if not valid_model_id(model_id):
        raise InvalidModelId(f"not a model id: {model_id!r}")
    local = card_path(model_id, Path(cards_dir))
    if local.is_file():
        return local.read_text(encoding="utf-8")
    if fetch is None:
        raise CardNotFound(f"no local card for {model_id} in {cards_dir}, and fetching is off")
    return fetch(card_url(model_id))[:MAX_CARD_BYTES]


def http_fetch(url: str) -> str:  # pragma: no cover - live only
    import urllib.request

    if not url.startswith(f"{HOST}/"):
        raise InvalidModelId(f"refusing to fetch outside {HOST}: {url!r}")
    with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 - the host is fixed above
        data: bytes = resp.read(MAX_CARD_BYTES)
    return data.decode("utf-8", "replace")
