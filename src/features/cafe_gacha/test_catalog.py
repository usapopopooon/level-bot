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
    assert all(card.draw_reward_xp > PAID_DRAW_COST_XP for card in CARDS)
    assert (
        next(card for card in CARDS if card.key == "house-blend").draw_reward_xp == 50
    )


def test_k_brot_uses_historical_name_and_description() -> None:
    card = next(card for card in CARDS if card.key == "k-pan")

    assert card.name == "Kブロート"
    assert card.description == "ジャガイモでかさ増しされた、戦時下の代用パン。"


def test_draw_rewards_guarantee_positive_paid_balance() -> None:
    assert {card.rarity: card.draw_reward_xp for card in CARDS} == {
        "C": 25,
        "UC": 30,
        "R": 50,
        "SR": 100,
        "SSR": 300,
    }


def test_exchange_rewards_match_draw_rewards() -> None:
    assert all(card.exchange_xp == card.draw_reward_xp for card in CARDS)


def test_public_rarity_labels_use_normal_naming() -> None:
    assert rarity_label("C") == "N"
    assert rarity_label("UC") == "HN"
    assert rarity_label("R") == "R"
    assert rarity_label("SR") == "SR"
    assert rarity_label("SSR") == "SSR"


def test_all_duplicate_paid_draw_has_double_average_reward() -> None:
    maximum_return = (
        sum(card.weight * (card.draw_reward_xp + card.exchange_xp) for card in CARDS)
        / TOTAL_WEIGHT
    )

    assert maximum_return == pytest.approx(72.0)
    assert maximum_return > PAID_DRAW_COST_XP


@pytest.mark.parametrize("value", [-1, TOTAL_WEIGHT])
def test_select_card_rejects_values_outside_table(value: int) -> None:
    with pytest.raises(ValueError):
        select_card(value)
