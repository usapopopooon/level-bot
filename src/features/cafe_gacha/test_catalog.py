from collections import Counter, defaultdict
from pathlib import Path

import pytest

from src.features.cafe_gacha.catalog import (
    CARDS,
    CARDS_BY_KEY,
    CARDS_BY_RARITY,
    FOOD_CARD_KEYS,
    PAID_DRAW_COST_XP,
    RARITY_ORDER,
    TOTAL_WEIGHT,
    rarity_label,
    select_card,
    select_card_for_collection,
    select_unowned_card,
)


def test_catalog_weights_cover_exact_range() -> None:
    assert sum(card.weight for card in CARDS) == TOTAL_WEIGHT
    start = 0
    for card in CARDS:
        assert select_card(start) == card
        assert select_card(start + card.weight - 1) == card
        start += card.weight
    assert start == TOTAL_WEIGHT


def test_catalog_has_100_unique_cards_with_discord_sized_rarity_groups() -> None:
    assert len(CARDS) == 100
    assert len(CARDS_BY_KEY) == 100
    assert len({card.name for card in CARDS}) == 100
    assert all(len(CARDS_BY_RARITY[rarity]) <= 25 for rarity in RARITY_ORDER)


def test_catalog_balances_drinks_with_29_food_cards() -> None:
    assert len(FOOD_CARD_KEYS) == 29
    assert len(CARDS_BY_KEY.keys() - FOOD_CARD_KEYS) == 71
    assert {
        "discount-roll-cake",
        "butter-toast",
        "canele",
        "sachertorte",
        "woolton-pie",
        "kommissbrot",
        "national-loaf",
        "hardtack",
    } <= FOOD_CARD_KEYS


def test_catalog_includes_requested_historical_food_names() -> None:
    actual = {
        key: CARDS_BY_KEY[key].name
        for key in ("woolton-pie", "kommissbrot", "national-loaf", "hardtack")
    }

    assert actual == {
        "woolton-pie": "ウールトンパイ",
        "kommissbrot": "コミスブロート",
        "national-loaf": "ナショナル・ローフ",
        "hardtack": "ハードタック",
    }


def test_rarity_distribution_keeps_the_existing_economy() -> None:
    weights_by_rarity: defaultdict[str, int] = defaultdict(int)
    for card in CARDS:
        weights_by_rarity[card.rarity] += card.weight

    assert dict(weights_by_rarity) == {
        "C": 6500,
        "UC": 2400,
        "R": 800,
        "SR": 250,
        "SSR": 50,
    }


def test_catalog_includes_mainstream_and_specialty_names() -> None:
    expected_keys = {
        "brazil-santos-no2",
        "colombia-supremo",
        "ethiopia-yirgacheffe-g1",
        "jamaica-blue-mountain-no1",
        "panama-geisha",
        "darjeeling-first-flush",
        "ceylon-uva",
        "longjing",
        "hon-gyokuro",
        "masala-chai",
        "wild-kopi-luwak",
    }

    assert expected_keys <= CARDS_BY_KEY.keys()


def test_unowned_bonus_preserves_rarity_rates_and_favors_missing_cards() -> None:
    collected = {card.key for card in CARDS if card.key != "sale-tea-bags"}
    selections = Counter(
        select_card_for_collection(value, collected).key
        for value in range(TOTAL_WEIGHT)
    )
    rarity_counts = Counter(
        select_card_for_collection(value, collected).rarity
        for value in range(TOTAL_WEIGHT)
    )

    assert rarity_counts == {"C": 6500, "UC": 2400, "R": 800, "SR": 250, "SSR": 50}
    assert selections["sale-tea-bags"] > selections["spent-tea"]


def test_endgame_selector_always_returns_an_unowned_card() -> None:
    unowned_keys = {"panama-geisha", "legendary-tea-leaves"}
    collected = CARDS_BY_KEY.keys() - unowned_keys

    assert {
        select_unowned_card(value, collected).key for value in range(TOTAL_WEIGHT)
    } == unowned_keys


def test_every_catalog_image_exists_and_is_square() -> None:
    from PIL import Image

    asset_dir = Path(__file__).parent / "assets"
    for card in CARDS:
        path = asset_dir / card.image_filename
        assert path.is_file(), path
        with Image.open(path) as image:
            assert image.format == "JPEG"
            assert image.width == image.height


def test_catalog_images_do_not_have_a_pale_outer_matte() -> None:
    from PIL import Image

    asset_dir = Path(__file__).parent / "assets"
    for card in CARDS:
        path = asset_dir / card.image_filename
        with Image.open(path) as source:
            image = source.convert("RGB")
            band = max(1, image.width // 32)
            border_pixels = [
                *image.crop((0, 0, image.width, band)).getdata(),
                *image.crop(
                    (0, image.height - band, image.width, image.height)
                ).getdata(),
                *image.crop((0, band, band, image.height - band)).getdata(),
                *image.crop(
                    (image.width - band, band, image.width, image.height - band)
                ).getdata(),
            ]
            white_ratio = sum(
                red >= 240 and green >= 240 and blue >= 240
                for red, green, blue in border_pixels
            ) / len(border_pixels)
            corner = max(1, image.width // 8)
            corner_pixels = [
                *image.crop((0, 0, corner, corner)).getdata(),
                *image.crop((image.width - corner, 0, image.width, corner)).getdata(),
                *image.crop((0, image.height - corner, corner, image.height)).getdata(),
                *image.crop(
                    (
                        image.width - corner,
                        image.height - corner,
                        image.width,
                        image.height,
                    )
                ).getdata(),
            ]
            corner_brightness = sum(
                (red + green + blue) / 3 for red, green, blue in corner_pixels
            ) / len(corner_pixels)

        assert white_ratio < 0.1, (
            f"{card.image_filename} has a white outer matte "
            f"({white_ratio:.1%} of border pixels)"
        )
        assert corner_brightness < 125, (
            f"{card.image_filename} has a pale outer matte "
            f"(mean corner brightness {corner_brightness:.1f})"
        )


def test_every_card_guarantees_draw_xp() -> None:
    assert all(card.draw_reward_xp > PAID_DRAW_COST_XP for card in CARDS)
    assert (
        next(card for card in CARDS if card.key == "house-blend").draw_reward_xp == 60
    )


def test_n_cards_give_everyday_items_a_gag_framing() -> None:
    expected_names = {
        "cold-black-tea": "すっかり冷めた紅茶",
        "100-yen-black-tea": "百円ショップの徳用紅茶",
        "discount-roll-cake": "半額ロールケーキ",
        "100-yen-cookie": "袋の底の割れクッキー",
        "mugicha": "昨日の麦茶",
        "rooibos-tea": "いただきもののルイボスティー",
        "mint-tea": "庭で増えすぎたミントティー",
        "cocoa": "底に粉が残ったココア",
    }

    assert {key: CARDS_BY_KEY[key].name for key in expected_names} == expected_names
    assert all(CARDS_BY_KEY[key].rarity == "C" for key in expected_names)


def test_k_brot_uses_historical_name_with_n_gag_description() -> None:
    card = next(card for card in CARDS if card.key == "k-pan")

    assert card.name == "Kブロート"
    assert card.description == "ジャガイモでかさ増し。パンだと言い張る気持ちはある。"


def test_draw_rewards_guarantee_positive_paid_balance() -> None:
    assert {card.rarity: card.draw_reward_xp for card in CARDS} == {
        "C": 25,
        "UC": 30,
        "R": 60,
        "SR": 150,
        "SSR": 500,
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

    assert maximum_return == pytest.approx(69.0)
    assert maximum_return > PAID_DRAW_COST_XP


@pytest.mark.parametrize("value", [-1, TOTAL_WEIGHT])
def test_select_card_rejects_values_outside_table(value: int) -> None:
    with pytest.raises(ValueError):
        select_card(value)
