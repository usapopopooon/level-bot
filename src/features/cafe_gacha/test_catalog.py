import pytest

from src.features.cafe_gacha.catalog import (
    CARDS,
    PAID_DRAW_COST_XP,
    TOTAL_WEIGHT,
    rarity_label,
    select_card,
)


def test_catalog_weights_cover_exact_range() -> None:
    assert sum(card.weight for card in CARDS) == TOTAL_WEIGHT
    start = 0
    for card in CARDS:
        assert select_card(start) == card
        assert select_card(start + card.weight - 1) == card
        start += card.weight
    assert start == TOTAL_WEIGHT


def test_every_card_guarantees_draw_xp() -> None:
    assert all(card.draw_reward_xp > 0 for card in CARDS)
    assert (
        next(card for card in CARDS if card.key == "house-blend").draw_reward_xp == 15
    )


def test_only_common_rarity_is_presented_as_normal() -> None:
    assert rarity_label("C") == "N"
    assert rarity_label("UC") == "UC"
    assert rarity_label("R") == "R"
    assert rarity_label("SR") == "SR"
    assert rarity_label("SSR") == "SSR"


def test_paid_draw_cannot_generate_xp_on_average_even_if_every_card_is_duplicate() -> (
    None
):
    maximum_return = (
        sum(card.weight * (card.draw_reward_xp + card.exchange_xp) for card in CARDS)
        / TOTAL_WEIGHT
    )

    assert maximum_return < PAID_DRAW_COST_XP


@pytest.mark.parametrize("value", [-1, TOTAL_WEIGHT])
def test_select_card_rejects_values_outside_table(value: int) -> None:
    with pytest.raises(ValueError):
        select_card(value)
