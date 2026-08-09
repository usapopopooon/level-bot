import pytest

from src.features.cafe_gacha.catalog import CARDS, TOTAL_WEIGHT, select_card


def test_catalog_weights_cover_exact_range() -> None:
    assert sum(card.weight for card in CARDS) == TOTAL_WEIGHT
    start = 0
    for card in CARDS:
        assert select_card(start) == card
        assert select_card(start + card.weight - 1) == card
        start += card.weight
    assert start == TOTAL_WEIGHT


@pytest.mark.parametrize("value", [-1, TOTAL_WEIGHT])
def test_select_card_rejects_values_outside_table(value: int) -> None:
    with pytest.raises(ValueError):
        select_card(value)
