from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.sets import SETS, completed_set_keys


def test_set_recipes_only_reference_catalog_cards() -> None:
    assert len(SETS) == 28
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
    } <= {item.key for item in SETS}


def test_completed_sets_use_lifetime_card_keys() -> None:
    owned = {"k-pan", "instant-coffee", "jam-toast", "sunflower-coffee"}

    assert completed_set_keys(owned) == {"economy-morning"}
