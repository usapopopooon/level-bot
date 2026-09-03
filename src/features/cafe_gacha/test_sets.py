from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.sets import SETS, completed_set_keys


def test_set_recipes_only_reference_catalog_cards() -> None:
    assert len(SETS) == 54
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
        "archipelago-three-eras",
        "tokuhou-style-cafe",
        "enchanted-cafe",
        "lost-civilization-excavation",
        "portal-linked-fungal-cafe",
        "fungal-realms-drink-bar",
        "nile-riverside-temple-cafe",
        "two-rivers-clay-tablet-cafe",
        "indus-brick-city-cafe",
        "yellow-river-bronze-cafe",
        "japanese-everyday-tea-drawer",
        "japanese-regional-tea-tour",
        "chinese-six-tea-colors",
        "chinese-famous-tea-mountains",
        "taiwan-high-mountain-route",
        "taiwan-tea-garden-ten-seats",
        "himalayan-tea-slopes",
        "ceylon-seven-regions",
        "black-sea-caucasus-tea-road",
        "world-tea-fields",
    } <= {item.key for item in SETS}


def test_ancient_japanese_era_set_follows_the_three_periods() -> None:
    era_set = next(item for item in SETS if item.key == "archipelago-three-eras")

    assert era_set.name == "列島・三つの時代"
    assert era_set.required_keys == (
        "jomon-pottery-nut-soup",
        "yayoi-jar-red-rice-porridge",
        "kofun-keyhole-tomb-cake",
    )


def test_ordinary_tea_sets_cover_all_66_new_teas() -> None:
    expected_recipes = {
        "japanese-everyday-tea-drawer": (
            "bancha",
            "kukicha",
            "karigane",
            "konacha",
            "mecha",
            "tamaryokucha",
            "kamairicha",
            "kyobancha",
            "kaga-boucha",
            "wakoucha",
        ),
        "japanese-regional-tea-tour": (
            "sayama-cha",
            "yame-cha",
            "ureshino-cha",
            "chiran-cha",
            "ise-cha",
            "uji-sencha",
        ),
        "chinese-six-tea-colors": (
            "dongting-biluochun",
            "bai-mudan",
            "junshan-yinzhen",
            "wuyi-rougui",
            "jin-jun-mei",
            "raw-puerh",
        ),
        "chinese-famous-tea-mountains": (
            "huangshan-maofeng",
            "luan-guapian",
            "taiping-houkui",
            "xinyang-maojian",
            "anji-baicha",
            "shou-mei",
            "huoshan-huangya",
            "phoenix-dancong",
            "wuyi-shuixian",
            "dianhong",
        ),
        "taiwan-high-mountain-route": (
            "alishan-high-mountain",
            "lishan-high-mountain",
            "shanlinxi-high-mountain",
            "dayuling-high-mountain",
        ),
        "taiwan-tea-garden-ten-seats": (
            "wenshan-baozhong",
            "muzha-tieguanyin",
            "alishan-high-mountain",
            "lishan-high-mountain",
            "shanlinxi-high-mountain",
            "jinxuan-tea",
            "sijichun-tea",
            "taiwan-ruby-black-tea",
            "honey-aroma-black-tea",
            "dayuling-high-mountain",
        ),
        "himalayan-tea-slopes": (
            "assam-orthodox",
            "darjeeling-autumnal",
            "dooars-terai",
            "kangra-black-tea",
            "sikkim-temi",
            "nepal-ilam",
            "nepal-panchthar-orthodox",
            "darjeeling-monsoon-flush",
        ),
        "ceylon-seven-regions": (
            "ceylon-nuwara-eliya",
            "ceylon-uda-pussellawa",
            "ceylon-uva",
            "ceylon-dimbula",
            "ceylon-kandy",
            "ceylon-sabaragamuwa",
            "ceylon-ruhuna",
        ),
        "black-sea-caucasus-tea-road": (
            "rize-tea",
            "georgian-black-tea",
            "azerbaijan-black-tea",
        ),
        "world-tea-fields": (
            "kenya-black-tea",
            "rwanda-black-tea",
            "malawi-black-tea",
            "java-black-tea",
            "vietnam-lotus-tea",
            "boseong-green-tea",
            "jeju-green-tea",
        ),
    }
    actual = {item.key: item.required_keys for item in SETS}

    assert {key: actual[key] for key in expected_recipes} == expected_recipes
    covered_keys = {
        card_key
        for set_key in expected_recipes
        for card_key in actual[set_key]
        if card_key != "ceylon-uva"
    }
    assert len(covered_keys) == 66


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


def test_portal_linked_fungal_cafe_bridges_both_mushroom_worlds() -> None:
    item = next(item for item in SETS if item.key == "portal-linked-fungal-cafe")

    assert item.name == "菌糸界をつなぐポータルカフェ"
    assert item.required_keys == (
        "brown-mushroom-cream-potage",
        "red-mushroom-croque-monsieur",
        "suspicious-mushroom-stew",
        "crimson-fungus-inferno-gratin",
        "warped-fungus-soulflame-pasta",
        "nether-dual-fungus-fondue",
    )


def test_fungal_realms_drink_bar_collects_one_drink_from_each_forest() -> None:
    item = next(item for item in SETS if item.key == "fungal-realms-drink-bar")

    assert item.name == "菌糸界のドリンクバー"
    assert item.required_keys == (
        "brown-mushroom-roast-latte",
        "crimson-fungus-magma-chai",
        "warped-fungus-soulflame-soda",
    )


def test_nile_riverside_temple_cafe_spans_every_rarity_from_n_to_ssr() -> None:
    item = next(item for item in SETS if item.key == "nile-riverside-temple-cafe")

    assert item.name == "ナイル河畔の神殿カフェ"
    assert item.required_keys == (
        "reed-basket-dates-and-figs",
        "nile-morning-dew-water",
        "stone-ground-emmer-honey-bread",
        "pomegranate-mint-pitcher",
        "desert-honey-nut-sweets",
        "nile-date-milk",
        "blue-lotus-fig-temple-tart",
        "desert-sunset-pomegranate-tea",
        "royal-golden-pyramid-cake",
        "starry-blue-lotus-soda",
    )


def test_two_rivers_clay_tablet_cafe_spans_every_rarity_from_n_to_ssr() -> None:
    item = next(item for item in SETS if item.key == "two-rivers-clay-tablet-cafe")

    assert item.name == "二河流域の粘土板カフェ"
    assert item.required_keys == (
        "uruk-barley-flatbread",
        "reed-straw-barley-beer",
        "date-syrup-sesame-sweets",
        "tigris-pomegranate-water",
        "twice-baked-malt-honey-rusks",
        "babylon-date-malt-drink",
        "clay-tablet-lamb-beet-stew",
        "ur-golden-straw-barley-beer",
        "ishtar-gate-lapis-cake",
        "ziggurat-stargazer-cordial",
    )


def test_indus_brick_city_cafe_spans_every_rarity_from_n_to_ssr() -> None:
    item = next(item for item in SETS if item.key == "indus-brick-city-cafe")

    assert item.name == "インダス煉瓦都市カフェ"
    assert item.required_keys == (
        "harappa-wheat-barley-porridge",
        "painted-pottery-millet-water",
        "sesame-jujube-grain-cakes",
        "mohenjo-daro-cool-milk",
        "indus-pulse-barley-claypot",
        "harappa-melon-grape-cordial",
        "unicorn-seal-sesame-cake",
        "great-bath-jade-milk",
        "mohenjo-daro-brick-city-cake",
        "indus-seal-starlight-cordial",
    )


def test_yellow_river_bronze_cafe_spans_every_rarity_from_n_to_ssr() -> None:
    item = next(item for item in SETS if item.key == "yellow-river-bronze-cafe")

    assert item.name == "黄河と青銅の文明茶房"
    assert item.required_keys == (
        "yellow-river-millet-porridge",
        "painted-pottery-millet-drink",
        "stone-ground-millet-steamed-cakes",
        "jiahu-rice-honey-fruit-brew",
        "bronze-ding-herb-meat-stew",
        "anyang-herbal-millet-wine",
        "jade-bi-honey-cake",
        "oracle-bone-flower-rice-wine",
        "nine-ding-jade-grain-cake",
        "celestial-bronze-jue-cordial",
    )


def test_completed_sets_use_lifetime_card_keys() -> None:
    owned = {"k-pan", "instant-coffee", "jam-toast", "sunflower-coffee"}

    assert completed_set_keys(owned) == {"economy-morning"}
