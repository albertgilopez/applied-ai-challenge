"""T4: package URLs and the source link derived from them (STORY-001 DR-7, S1-18)."""
from pathlib import Path

import pytest
import yaml

from core.purl import Purl, parse_purl, url_for

CASES = yaml.safe_load((Path(__file__).resolve().parents[2] / "stories" / "STORY-001.cases.yaml").read_text(encoding="utf-8"))
PURL_ROWS = [r for c in CASES if c["id"] == "S1-18" for r in c["rows"] if "purl" in r]


def test_parse_splits_the_parts_and_decodes():
    assert parse_purl("pkg:npm/%40scope/pkg@1.0.0?arch=x#sub") == Purl("npm", "@scope", "pkg", "1.0.0")
    assert parse_purl("pkg:PyPI/requests") == Purl("pypi", None, "requests", None)


@pytest.mark.parametrize("row", PURL_ROWS, ids=lambda r: r["purl"])
def test_source_link_from_purl(row):  # S1-18
    assert url_for(row["purl"]) == row["expected"]


@pytest.mark.parametrize("bad", ["", "requests", "pkg:", "pkg:pypi", "pkg:pypi/"])
def test_a_malformed_purl_gives_no_link(bad):
    assert url_for(bad) is None


def test_an_unknown_type_gives_no_link():
    assert url_for("pkg:cargo/serde@1.0.0") is None
