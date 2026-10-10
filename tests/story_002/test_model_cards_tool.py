"""STORY-002 S2-06: the card tool takes a model id, never a URL, and reads from a fixed place (D-04)."""

from pathlib import Path

import pytest
import yaml

from agent.model_cards import CardNotFound, InvalidModelId, card_path, load_card, valid_model_id

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "samples" / "model-cards"
CASES = yaml.safe_load((ROOT / "stories" / "STORY-002.cases.yaml").read_text("utf-8"))
CASE = next(c for c in CASES if c["id"] == "S2-06")


@pytest.mark.parametrize("bad", CASE["tool_input"])
def test_s2_06_anything_that_is_not_a_model_id_is_refused(bad):
    assert not valid_model_id(bad)
    with pytest.raises(InvalidModelId):
        load_card(bad, CARDS)


@pytest.mark.parametrize("good", CASE["accepted"])
def test_s2_06_model_ids_are_accepted_and_read_locally(good):
    assert valid_model_id(good)
    assert card_path(good, CARDS).parent == CARDS
    assert "license" in load_card(good, CARDS).lower()


def test_a_missing_card_is_not_fetched_unless_a_fetcher_is_given(tmp_path):
    with pytest.raises(CardNotFound):
        load_card("org/missing", tmp_path)
    seen = []

    def fetch(url: str) -> str:
        seen.append(url)
        return "---\nlicense: mit\n---\n"

    assert load_card("org/missing", tmp_path, fetch=fetch).startswith("---")
    assert seen == ["https://huggingface.co/org/missing/raw/main/README.md"]  # the host is fixed by the code
