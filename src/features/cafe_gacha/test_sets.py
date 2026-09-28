from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.sets import SETS, completed_set_keys


def test_set_recipes_only_reference_catalog_cards() -> None:
    assert len(SETS) == 73
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
        "soviet-shortage-kitchen",
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
        "night-train-dining-car",
        "school-lunch-memories",
        "depression-era-pantry",
        "drugstore-soda-fountain",
        "polar-expedition-provision-box",
        "vending-machine-corner",
        "post-bath-cold-case",
        "final-screening-concession",
        "night-shift-break-room",
        "transfer-stop-meals",
        "levant-gulf-cafe-table",
        "steppe-oasis-cafe-table",
    } <= {item.key for item in SETS}


def test_steppe_and_oasis_cafe_table_requires_all_six_cards() -> None:
    cafe_set = next(item for item in SETS if item.key == "steppe-oasis-cafe-table")

    assert cafe_set.name == "草原とオアシスの喫茶卓"
    assert cafe_set.required_keys == (
        "toasted-millet-zhent",
        "street-maksym",
        "navat-green-tea",
        "tandoor-samsa",
        "pamir-shirchoy",
        "festive-pishme",
    )
    all_keys = set(cafe_set.required_keys)
    assert cafe_set.key in completed_set_keys(all_keys)
    for missing_key in all_keys:
        assert cafe_set.key not in completed_set_keys(all_keys - {missing_key})


def test_levant_and_gulf_cafe_table_collects_all_six_cards() -> None:
    cafe_set = next(item for item in SETS if item.key == "levant-gulf-cafe-table")

    assert cafe_set.name == "レヴァントと湾岸の喫茶卓"
    assert cafe_set.required_keys == (
        "gulf-cardamom-gahwa",
        "roadside-karak-chai",
        "pine-nut-jallab",
        "zaatar-manakish",
        "wood-mold-maamoul",
        "hot-knafeh",
    )


def test_ancient_japanese_era_set_follows_the_three_periods() -> None:
    era_set = next(item for item in SETS if item.key == "archipelago-three-eras")

    assert era_set.name == "列島・三つの時代"
    assert era_set.required_keys == (
        "jomon-pottery-nut-soup",
        "yayoi-jar-red-rice-porridge",
        "kofun-keyhole-tomb-cake",
    )


def test_soviet_shortage_kitchen_set_collects_all_six_n_foods() -> None:
    shortage_set = next(item for item in SETS if item.key == "soviet-shortage-kitchen")

    assert shortage_set.name == "もの不足のソ連台所"
    assert shortage_set.required_keys == (
        "black-bread-sunflower-oil",
        "sugared-macaroni",
        "thin-cabbage-canteen-soup",
        "thursday-fish-cutlet",
        "tomato-sprat-black-bread",
        "scrap-kartoshka-cake",
    )
    assert {CARDS_BY_KEY[key].rarity for key in shortage_set.required_keys} == {"C"}


def test_five_new_sets_collect_each_series_in_display_order() -> None:
    expected = {
        "night-train-dining-car": (
            "終着駅までの喫茶時間",
            (
                "night-train-paper-cup-coffee",
                "waiting-room-aluminum-teapot-tea",
                "dry-trolley-sandwich",
                "dining-car-consomme",
                "sleeper-train-breakfast-toast",
                "dining-car-beef-stew",
                "first-class-silver-breakfast",
            ),
        ),
        "school-lunch-memories": (
            "昔の学校給食",
            (
                "school-lunch-milmake",
                "school-lunch-frozen-mandarin",
                "school-lunch-soft-noodles",
                "school-lunch-fried-bread",
            ),
        ),
        "depression-era-pantry": (
            "不況期の節約料理",
            (
                "depression-water-pie",
                "depression-mock-apple-pie",
                "hoover-stew",
            ),
        ),
        "drugstore-soda-fountain": (
            "古い薬局のソーダファウンテン",
            (
                "soda-fountain-malted-milk",
                "soda-fountain-egg-cream",
                "soda-fountain-phosphate-soda",
            ),
        ),
        "polar-expedition-provision-box": (
            "極地探検隊の食料箱",
            (
                "polar-pemmican",
                "polar-condensed-milk-tea",
                "polar-compressed-soup",
                "polar-frozen-biscuits",
            ),
        ),
    }
    actual = {item.key: (item.name, item.required_keys) for item in SETS}

    assert {key: actual[key] for key in expected} == expected


def test_four_everyday_place_sets_collect_each_series_in_display_order() -> None:
    expected = {
        "vending-machine-corner": (
            "古い自販機コーナー",
            (
                "vending-paper-cup-coffee",
                "vending-glass-bottle-cola",
                "vending-tempura-udon",
                "vending-boxed-hamburger",
                "vending-cup-noodles",
                "vending-ham-cheese-toast",
            ),
        ),
        "post-bath-cold-case": (
            "湯上がりの冷蔵ケース",
            (
                "bathhouse-coffee-milk",
                "bathhouse-fruit-milk",
                "bathhouse-ramune",
                "bathhouse-ice-bar",
            ),
        ),
        "final-screening-concession": (
            "最終上映の映画館売店",
            (
                "cinema-paper-bag-popcorn",
                "cinema-melted-ice-cola",
                "cinema-set-nachos",
                "cinema-last-hot-dog",
            ),
        ),
        "night-shift-break-room": (
            "夜勤休憩室",
            (
                "break-room-stick-coffee",
                "break-room-vending-corn-soup",
                "break-room-late-night-cup-noodles",
                "break-room-gift-manju",
                "break-room-named-pudding",
            ),
        ),
    }
    actual = {item.key: (item.name, item.required_keys) for item in SETS}

    assert {key: actual[key] for key in expected} == expected


def test_transfer_stop_set_collects_all_six_n_meals() -> None:
    transfer_set = next(item for item in SETS if item.key == "transfer-stop-meals")

    assert transfer_set.name == "乗り換えの腹ごしらえ"
    assert transfer_set.required_keys == (
        "bus-center-yellow-curry",
        "platform-dashi-chuka-soba",
        "giant-karaage-soba",
        "sweet-savory-kashiwa-udon",
        "pre-departure-flat-udon",
        "station-tricolor-kashiwa-meshi",
    )
    assert {CARDS_BY_KEY[key].rarity for key in transfer_set.required_keys} == {"C"}


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


def test_european_drink_sets_cover_35_cards_and_require_every_ingredient() -> None:
    expected = {
        "central-europe-soda-counter": (
            "中欧の炭酸カウンター",
            (
                "kofola",
                "cockta",
                "almdudler",
                "rivella",
                "paulaner-spezi",
                "club-mate",
                "bionade-elderberry",
            ),
        ),
        "island-soft-drink-shelf": (
            "島々のソフトドリンク棚",
            (
                "kinnie",
                "irn-bru",
                "vimto",
                "fentimans-dandelion-burdock",
                "brisa-maracuja",
            ),
        ),
        "italian-aperitivo-trio": (
            "夕方のアペリティーヴォ",
            (
                "crodino",
                "sanbitter-rosso",
                "sanpellegrino-chinotto",
            ),
        ),
        "european-sweet-cold-case": (
            "欧州の甘い冷蔵ケース",
            (
                "pommac",
                "apotekarnes-julmust",
                "chocomel",
                "fristi",
                "cacolac",
            ),
        ),
        "eastern-europe-local-bottles": (
            "東欧と周辺の地元ボトル",
            (
                "vinea",
                "traubisoda",
                "hellena-oranzada",
                "tymbark-apple-mint",
                "kubus-apple-carrot-peach",
                "pipi",
                "brifcor",
                "zhyvchyk",
                "baikal",
            ),
        ),
        "eastern-europe-pantry-drinks": (
            "東欧とバルトの台所の一杯",
            (
                "bread-kvass",
                "uzvar",
                "socata",
                "ryazhenka",
                "kama-kefir",
                "sbiten",
            ),
        ),
    }
    actual = {item.key: (item.name, item.required_keys) for item in SETS}

    assert {key: actual[key] for key in expected} == expected
    all_keys = [key for _, keys in expected.values() for key in keys]
    assert len(all_keys) == len(set(all_keys)) == 35
    for set_key, (_, keys) in expected.items():
        assert set_key in completed_set_keys(set(keys))
        for missing_key in keys:
            assert set_key not in completed_set_keys(set(keys) - {missing_key})


def test_completed_sets_use_lifetime_card_keys() -> None:
    owned = {"k-pan", "instant-coffee", "jam-toast", "sunflower-coffee"}

    assert completed_set_keys(owned) == {"economy-morning"}
