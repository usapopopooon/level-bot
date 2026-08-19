from collections import Counter, defaultdict
from pathlib import Path

import pytest

from src.features.cafe_gacha.catalog import (
    CARD_KEYS_BY_TAG,
    CARD_TAGS_BY_KEY,
    CARDS,
    CARDS_BY_KEY,
    EXCHANGE_XP_BY_RARITY,
    FOOD_CARD_KEYS,
    PAID_DRAW_COST_XP,
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


def test_catalog_has_261_unique_cards() -> None:
    assert len(CARDS) == 261
    assert len(CARDS_BY_KEY) == 261
    assert len({card.name for card in CARDS}) == 261


def test_catalog_keeps_drinks_as_the_clear_majority() -> None:
    assert len(FOOD_CARD_KEYS) == 104
    assert len(CARDS_BY_KEY.keys() - FOOD_CARD_KEYS) == 157
    assert len(CARDS_BY_KEY.keys() - FOOD_CARD_KEYS) / len(CARDS) > 0.6
    assert {
        "discount-roll-cake",
        "butter-toast",
        "canele",
        "sachertorte",
        "woolton-pie",
        "kommissbrot",
        "national-loaf",
        "hardtack",
        "shimeji-hill",
        "chikuwa-village",
        "capybara-break",
        "emperors-rich-cup",
        "shrinkflation-sandwich",
        "self-help-soup",
        "downsized-cream-puff",
        "compliance-cookie",
        "hollowed-out-mille-feuille",
        "endless-growth-pancakes",
        "tomorrows-bread",
        "koriyama-cream-box",
        "himeji-almond-toast",
        "ogura-toast",
        "teppan-napolitan",
        "gifu-chawanmushi-morning",
        "kochi-miso-soup-morning",
        "nagasaki-eating-milkshake",
        "okinawa-zenzai",
        "okaisan",
        "bote-cha",
        "botebote-cha",
        "sapporo-shime-parfait",
        "oralalala-cookie-sandwich",
        "cream-left-cookie-sandwich",
        "photo-wait-fries",
        "last-cookie",
        "checkout-financier",
        "phone-first-parfait",
        "sound-hired-cookie",
        "shop-sized-one-bite",
        "pudding-landing-failure",
        "endless-cheese-photo-toast",
        "menu-photo-relative-plate",
        "grownup-candy-kit-plate",
        "glass-fruit-candy",
    } <= FOOD_CARD_KEYS


def test_catalog_tags_cover_the_four_specialist_leaderboards() -> None:
    assert {tag: len(keys) for tag, keys in CARD_KEYS_BY_TAG.items()} == {
        "coffee": 77,
        "tea": 63,
        "sweets": 57,
        "culture": 132,
    }
    assert CARD_TAGS_BY_KEY["coffee-leaf-tea"] == frozenset(
        {"coffee", "tea", "culture"}
    )
    assert CARD_TAGS_BY_KEY["scone"] == frozenset({"sweets"})
    assert CARD_TAGS_BY_KEY["pompeii-panis-quadratus"] == frozenset({"culture"})
    assert all(CARDS_BY_KEY.keys() >= keys for keys in CARD_KEYS_BY_TAG.values())


def test_catalog_includes_japanese_local_cafe_culture_cards() -> None:
    expected_by_rarity = {
        "C": {"tomorrows-bread", "reiko", "miko"},
        "UC": {
            "osaka-mixed-juice",
            "koriyama-cream-box",
            "himeji-almond-toast",
            "ogura-toast",
            "teppan-napolitan",
        },
        "R": {
            "gifu-chawanmushi-morning",
            "kochi-miso-soup-morning",
            "nagasaki-eating-milkshake",
            "okinawa-zenzai",
            "okaisan",
            "bote-cha",
            "botebote-cha",
            "bukubuku-cha",
            "sapporo-shime-parfait",
        },
    }

    for rarity, keys in expected_by_rarity.items():
        assert {CARDS_BY_KEY[key].rarity for key in keys} == {rarity}
        assert all("culture" in CARD_TAGS_BY_KEY[key] for key in keys)
    assert sum(map(len, expected_by_rarity.values())) == 17
    assert CARD_TAGS_BY_KEY["reiko"] == frozenset({"coffee", "culture"})
    assert CARD_TAGS_BY_KEY["bukubuku-cha"] == frozenset({"tea", "culture"})


def test_catalog_includes_internet_and_cafe_comedy_cards() -> None:
    expected_by_rarity = {
        "C": {
            "oralalala-cookie-sandwich",
            "cream-left-cookie-sandwich",
            "photo-wait-fries",
            "last-cookie",
            "straw-defeated-tapioca",
            "former-latte-art-cloud",
            "saucer-escaped-coffee",
            "checkout-financier",
            "tiny-morning-coffee",
        },
        "UC": {
            "phone-first-parfait",
            "sound-hired-cookie",
            "shop-sized-one-bite",
            "pudding-landing-failure",
            "endless-cheese-photo-toast",
            "outlet-seat-coffee",
            "overlong-order-latte",
            "regulars-usual",
            "menu-photo-relative-plate",
        },
        "R": {
            "where-drink-ends-shake",
            "grownup-candy-kit-plate",
            "glass-fruit-candy",
        },
    }

    for rarity, keys in expected_by_rarity.items():
        assert {CARDS_BY_KEY[key].rarity for key in keys} == {rarity}
        assert all("culture" in CARD_TAGS_BY_KEY[key] for key in keys)
    assert sum(map(len, expected_by_rarity.values())) == 21
    assert CARD_TAGS_BY_KEY["former-latte-art-cloud"] == frozenset(
        {"coffee", "culture"}
    )
    assert CARD_TAGS_BY_KEY["glass-fruit-candy"] == frozenset({"sweets", "culture"})


def test_catalog_includes_thirty_new_historical_cafe_cards() -> None:
    expected_by_rarity = {
        "C": {
            "toast-water",
            "fig-coffee",
            "bark-bread",
            "yesterday-bread-pudding",
            "katemeshi",
            "suiton",
        },
        "UC": {
            "lemon-barley-water",
            "coffee-leaf-tea",
            "cacao-husk-tea",
            "boza",
            "egyptian-sobia",
            "sikhye",
            "mors",
            "pease-pudding",
            "acquacotta",
            "panzanella",
        },
        "R": {
            "kaffeost",
            "champurrado",
            "terere",
            "noon-chai",
            "kashmiri-kahwa",
            "oriental-beauty-tea",
            "mock-turtle-soup",
            "syllabub",
        },
        "SR": {
            "aged-liubao-tea",
            "nilgiri-frost-tea",
            "old-brown-java",
            "ecuador-typica-mejorado",
            "nesselrode-pudding",
        },
        "SSR": {"pompeii-panis-quadratus"},
    }

    for rarity, keys in expected_by_rarity.items():
        assert {CARDS_BY_KEY[key].rarity for key in keys} == {rarity}
    assert sum(map(len, expected_by_rarity.values())) == 30
    assert "戦時ケーキ" not in {card.name for card in CARDS}
    assert CARDS_BY_KEY["yesterday-bread-pudding"].description == (
        "固くなったパンを卵液で再雇用。二日目にして、やっと主役になった。"
    )


def test_catalog_separates_historical_anecdotes_from_irreplaceable_relics() -> None:
    ur_keys = {
        "beethoven-sixty-bean-coffee",
        "louis-xv-hot-chocolate",
        "jefferson-manuscript-ice-cream",
        "dickinson-window-gingerbread",
        "balzac-midnight-coffee",
    }
    mythic_keys = {
        "last-mother-tree-da-hong-pao",
        "boston-harbor-tea-vial",
        "antarctic-century-fruitcake",
    }

    assert {CARDS_BY_KEY[key].rarity for key in ur_keys} == {"UR"}
    assert {CARDS_BY_KEY[key].rarity for key in mythic_keys} == {"MYTHIC"}
    assert {CARDS_BY_KEY[key].weight for key in ur_keys} == {24}
    assert {CARDS_BY_KEY[key].weight for key in mythic_keys} == {10}
    assert all("culture" in CARD_TAGS_BY_KEY[key] for key in ur_keys | mythic_keys)


def test_catalog_adds_future_n_cards_and_missing_cafe_standards() -> None:
    future_n_keys = {
        "replica-coffee-c09",
        "molecular-reconstructed-milk-tea",
        "synthetic-cacao-cocoa",
        "rehydration-espresso-cube",
        "orbital-tube-tiramisu",
        "crumbless-scone",
        "cultivated-meat-pie",
        "cultured-protein-egg-sandwich",
        "precision-fermentation-cheese-toast",
        "mycelium-bacon-blt",
        "nutrient-polymer-jelly",
        "formula-replica-apple-pie",
    }
    standard_keys_by_rarity = {
        "UC": {
            "espresso",
            "cappuccino",
            "cafe-latte",
            "americano",
            "cafe-mocha",
            "fukamushi-sencha",
        },
        "R": {
            "flat-white",
            "typica",
            "bourbon",
            "caturra",
            "mundo-novo",
            "matcha",
            "kabusecha",
            "dong-ding-oolong",
            "ripe-puerh",
            "nilgiri-orthodox",
        },
        "SR": {"pacamara", "maragogipe", "baihao-yinzhen"},
    }

    assert {CARDS_BY_KEY[key].rarity for key in future_n_keys} == {"C"}
    for rarity, keys in standard_keys_by_rarity.items():
        assert {CARDS_BY_KEY[key].rarity for key in keys} == {rarity}
    assert sum(map(len, standard_keys_by_rarity.values())) == 19
    assert future_n_keys <= CARD_KEYS_BY_TAG["culture"]


def test_catalog_includes_original_product_wordplay_cards() -> None:
    expected = {
        "morning-tea": ("午前の紅茶", "C"),
        "moss-cola": ("苔コーラ", "C"),
        "red-cow-energy": ("赤べこエナジー", "C"),
        "shimeji-hill": ("しめじの丘", "C"),
        "chikuwa-village": ("竹輪の里", "C"),
        "unbroken-biscuit-sticks": ("ポキッとしなかった棒菓子", "C"),
        "capybara-break": ("カピバラの休憩", "UC"),
        "mistaken-donuts": ("ミスしたドーナツ", "UC"),
        "sure-to-break-wafer": ("きっと割れるウエハース", "UC"),
        "first-love-soda": ("白い初恋ソーダ", "R"),
        "stardust-cream-latte": ("星屑クリームラテ", "R"),
        "emperors-rich-cup": ("皇帝の濃厚カップ", "SR"),
    }

    assert {
        key: (CARDS_BY_KEY[key].name, CARDS_BY_KEY[key].rarity) for key in expected
    } == expected
    assert all(CARDS_BY_KEY[key].description for key in expected)


def test_catalog_includes_social_satire_cafe_cards() -> None:
    expected = {
        "shrinkflation-sandwich": (
            "実質据え置きサンド",
            "C",
            "パンの厚さは据え置き。具材だけが、ひと足先にスリムになった。",
        ),
        "payday-eve-blend": (
            "給料日前ブレンド",
            "C",
            "豆は三粒、ビスケットは半分。給料日はまだ湯気の向こう。",
        ),
        "self-help-soup": (
            "自助努力スープ",
            "C",
            "具材はそろえました。あとはお客様の自助努力で完成です。",
        ),
        "meeting-cooled-coffee": (
            "会議で冷めた珈琲",
            "C",
            "二時間の会議で決まったのは、次の会議の日程だけ。珈琲はとっくに冷めていた。",
        ),
        "ad-supported-water": (
            "広告つき天然水",
            "C",
            "無料の一杯。味わう前に、卓上広告を何枚かご覧ください。",
        ),
        "pending-breakfast": (
            "検討中のモーニング",
            "C",
            "パンと卵の是非を慎重に検討中。珈琲だけ先に冷めていく。",
        ),
        "downsized-cream-puff": (
            "中身を見直したシュークリーム",
            "C",
            "おいしさはそのまま。中身だけ、見直しました。",
        ),
        "sentiment-boost-latte": (
            "お気持ち増量ラテ",
            "C",
            "増えたのは泡ひとさじと、たいへん丁寧なお気持ち。",
        ),
        "uncancellable-tea": (
            "解約ページの見つからない紅茶",
            "UC",
            "一杯で始められるが、飲み終えるには長い手続きがいるらしい。",
        ),
        "subscription-sugar-cube": (
            "定額制角砂糖",
            "UC",
            "今月分は角砂糖一個。追加分は次回更新までお待ちください。",
        ),
        "ai-manager-blend": (
            "AI店長のおすすめブレンド",
            "UC",
            "三案を分析した結果、どれも同じ味に最適化された。",
        ),
        "five-star-hot-water": (
            "口コミ星五つの白湯",
            "UC",
            "星は五つ、味は白湯。評価欄だけがよく温まっている。",
        ),
        "mindful-instant-potage": (
            "丁寧な暮らしの即席ポタージュ",
            "UC",
            "粉末一袋を、花と銀皿と深呼吸で丁寧に仕上げた。",
        ),
        "compliance-cookie": (
            "コンプライアンス・クッキー",
            "UC",
            "角を落とし、長さを測り、誰にも引っかからない味になった。",
        ),
        "hollowed-out-mille-feuille": (
            "中抜きミルフィーユ",
            "R",
            "外周は立派。切ってみると、中央だけ効率よく抜かれている。",
        ),
        "trickle-down-coffee": (
            "トリクルダウン・コーヒー",
            "R",
            "上のポットは満杯。下のカップには、いつか一滴が届く予定。",
        ),
        "invisible-hand-kneaded-bread": (
            "見えざる手ごねパン",
            "R",
            "店主は触っていないと言う。粉の手形も、そう言っている。",
        ),
        "rating-economy-latte": (
            "評価経済ラテ",
            "R",
            "星を五つ浮かべれば、味の説明は短くて済む。",
        ),
        "outrage-roast-coffee": (
            "炎上焙煎珈琲",
            "R",
            "少し焦げた話題を、いちばん熱いうちにどうぞ。",
        ),
        "endless-growth-pancakes": (
            "無限成長パンケーキ",
            "SR",
            "前の皿より高く積めば、成長していることになるらしい。",
        ),
        "authority-approved-hot-water": (
            "世界的権威監修の白湯",
            "SR",
            "三人の権威が監修した、たいへん根拠のあるお湯。",
        ),
        "premium-ordinary-water": (
            "プレミアム普通水",
            "SR",
            "箱とリボンと証明書を外すと、よく冷えた普通の水。",
        ),
    }

    assert {
        key: (
            CARDS_BY_KEY[key].name,
            CARDS_BY_KEY[key].rarity,
            CARDS_BY_KEY[key].description,
        )
        for key in expected
    } == expected


def test_product_wordplay_descriptions_match_their_card_art() -> None:
    expected = {
        "morning-tea": "午後まで待てなかった。時計だけが、ずっと午前を指している。",
        "moss-cola": "底の丸いものは、まりもではないらしい。",
        "shimeji-hill": "焼き菓子だと説明された。土に見える部分も食べられるらしい。",
        "mistaken-donuts": "穴の位置も形も自由。店主は全部ドーナツだと言っている。",
        "first-love-soda": "添えられた手紙に差出人はいない。味だけは甘酸っぱい。",
        "stardust-cream-latte": (
            "金色の粒は食用らしい。星屑かどうかは聞かないでほしい。"
        ),
        "emperors-rich-cup": (
            "王冠は飴細工らしい。誰が皇帝なのかは教えてもらえなかった。"
        ),
    }

    assert {key: CARDS_BY_KEY[key].description for key in expected} == expected


def test_added_cards_focus_on_historical_food_and_cafe_culture() -> None:
    expected = {
        "pettuleipa",
        "horsebread",
        "turnip-winter-stew",
        "portable-soup",
        "posca",
        "east-frisian-tea",
        "st-helena-bourbon",
    }

    assert expected <= CARDS_BY_KEY.keys()
    assert all(CARDS_BY_KEY[key].description for key in expected)


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


def test_rarity_distribution_splits_the_former_ssr_rate() -> None:
    weights_by_rarity: defaultdict[str, int] = defaultdict(int)
    for card in CARDS:
        weights_by_rarity[card.rarity] += card.weight

    assert dict(weights_by_rarity) == {
        "C": 97_500,
        "UC": 36_000,
        "R": 12_000,
        "SR": 3_750,
        "SSR": 600,
        "UR": 120,
        "MYTHIC": 30,
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

    assert rarity_counts == {
        "C": 97_500,
        "UC": 36_000,
        "R": 12_000,
        "SR": 3_750,
        "SSR": 600,
        "UR": 120,
        "MYTHIC": 30,
    }
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
        "UR": 1_500,
        "MYTHIC": 5_000,
    }


def test_exchange_rewards_use_lower_separate_rates() -> None:
    assert EXCHANGE_XP_BY_RARITY == {
        "C": 5,
        "UC": 10,
        "R": 20,
        "SR": 50,
        "SSR": 150,
        "UR": 500,
        "MYTHIC": 1_500,
    }
    assert {card.rarity: card.exchange_xp for card in CARDS} == (EXCHANGE_XP_BY_RARITY)
    assert all(card.exchange_xp < card.draw_reward_xp for card in CARDS)


def test_public_rarity_labels_use_normal_naming() -> None:
    assert rarity_label("C") == "N"
    assert rarity_label("UC") == "HN"
    assert rarity_label("R") == "R"
    assert rarity_label("SR") == "SR"
    assert rarity_label("SSR") == "SSR"
    assert rarity_label("UR") == "UR"
    assert rarity_label("MYTHIC") == "幻"


def test_all_duplicate_paid_draw_has_rebalanced_average_reward() -> None:
    maximum_return = (
        sum(card.weight * (card.draw_reward_xp + card.exchange_xp) for card in CARDS)
        / TOTAL_WEIGHT
    )

    assert maximum_return == pytest.approx(46.0)
    assert maximum_return - PAID_DRAW_COST_XP == pytest.approx(26.0)
    assert maximum_return > PAID_DRAW_COST_XP


@pytest.mark.parametrize("value", [-1, TOTAL_WEIGHT])
def test_select_card_rejects_values_outside_table(value: int) -> None:
    with pytest.raises(ValueError):
        select_card(value)
