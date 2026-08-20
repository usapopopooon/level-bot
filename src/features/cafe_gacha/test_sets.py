from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.sets import SETS, completed_set_keys


def test_set_recipes_only_reference_catalog_cards() -> None:
    assert len(SETS) == 37
    assert len({item.key for item in SETS}) == len(SETS)
    assert all(len(item.required_keys) >= 2 for item in SETS)
    assert all(key in CARDS_BY_KEY for item in SETS for key in item.required_keys)
    assert {
        "creators-midnight",
        "recipes-in-handwriting",
        "unbrewable-treasures",
        "preserved-through-time",
        "espresso-family",
        "arabica-foundations",
        "giant-coffee-beans",
        "japanese-green-tea-basics",
        "tea-making-compass",
        "orbital-canteen-b",
        "replicator-standard-menu",
        "cellular-agriculture-morning",
        "synthetic-sweets-lab",
        "kansai-cafe-codewords",
        "regional-morning-border",
        "thought-it-was-a-drink",
        "bote-botebote-bukubuku-batabata",
        "black-white-grammar-lesson-one",
        "camera-ate-first",
        "last-ones-standing",
        "hired-for-something-else",
        "underfoot-cafe-comedy",
        "stone-and-fire-table",
        "tokuhou-style-cafe",
        "enchanted-cafe",
        "lost-civilization-excavation",
    } <= {item.key for item in SETS}


def test_stone_and_fire_table_follows_the_prehistoric_food_sequence() -> None:
    item = next(item for item in SETS if item.key == "stone-and-fire-table")

    assert item.name == "石と火の食卓"
    assert item.required_keys == (
        "dawn-fire-roast",
        "paleolithic-hunters-stone-plate",
        "neolithic-pottery-stew",
    )


def test_tokuhou_style_cafe_collects_only_the_six_health_label_cards() -> None:
    item = next(item for item in SETS if item.key == "tokuhou-style-cafe")

    assert item.name == "特保っぽいカフェ"
    assert item.required_keys == (
        "post-meal-clear-tea",
        "tummy-friendly-yogurt",
        "fat-conscious-cafe-latte",
        "sugar-conscious-kanten-jelly",
        "blood-pressure-conscious-cocoa",
        "double-function-morning",
    )


def test_enchanted_cafe_collects_the_three_enchanted_menus() -> None:
    item = next(item for item in SETS if item.key == "enchanted-cafe")

    assert item.name == "エンチャントされたカフェ"
    assert item.required_keys == (
        "enchanted-apple-tart",
        "enchanted-lapis-soda",
        "enchanted-honey-toast",
    )


def test_lost_civilization_excavation_follows_the_discovery_sequence() -> None:
    item = next(item for item in SETS if item.key == "lost-civilization-excavation")

    assert item.name == "失われた文明の発掘記録"
    assert item.required_keys == (
        "fossil-strata-mille-feuille",
        "ruins-excavation-tiramisu",
        "ooparts-celestial-disk-tart",
    )


def test_completed_sets_use_lifetime_card_keys() -> None:
    owned = {"k-pan", "instant-coffee", "jam-toast", "sunflower-coffee"}

    assert completed_set_keys(owned) == {"economy-morning"}
