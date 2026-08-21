"""既存カードを横断して集めるセットメニュー。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CafeSet:
    key: str
    name: str
    description: str
    required_keys: tuple[str, ...]


SETS: tuple[CafeSet, ...] = (
    CafeSet(
        "economy-morning",
        "ぎりぎりモーニング",
        "節約の工夫を一皿へ。",
        ("k-pan", "instant-coffee", "jam-toast"),
    ),
    CafeSet(
        "classic-morning",
        "王道の喫茶店モーニング",
        "厚切りトーストと珈琲で開店。",
        ("house-blend", "butter-toast", "egg-salad-sandwich"),
    ),
    CafeSet(
        "british-tea",
        "英国式ティータイム",
        "紅茶と軽食をきちんと揃える。",
        ("english-breakfast", "scone", "tea-sandwiches"),
    ),
    CafeSet(
        "milk-tea-trip",
        "世界のミルクティー巡り",
        "三つの街の甘く濃い一杯。",
        ("assam-ctc", "teh-tarik", "hong-kong-milk-tea"),
    ),
    CafeSet(
        "vietnam-cafe",
        "ベトナム喫茶紀行",
        "練乳と卵で楽しむ二つの珈琲。",
        ("vietnamese-iced-coffee", "vietnamese-egg-coffee"),
    ),
    CafeSet(
        "substitute-coffee",
        "豆なし珈琲研究会",
        "珈琲豆がなくても看板は下ろさない。",
        ("sunflower-coffee", "acorn-coffee", "dandelion-coffee"),
    ),
    CafeSet(
        "retro-desserts",
        "喫茶店の甘い三角形",
        "プリン、カヌレ、モンブラン。",
        ("custard-pudding", "canele", "mont-blanc"),
    ),
    CafeSet(
        "coffee-origins",
        "珈琲産地の旅",
        "南米・アフリカ・アジアを一棚で。",
        ("brazil-santos-no2", "ethiopia-yirgacheffe-g1", "sumatra-mandheling-g1"),
    ),
    CafeSet(
        "fermented-tea",
        "発酵茶の里めぐり",
        "土地ごとの乳酸発酵茶を飲み比べ。",
        ("goishicha", "awabancha", "batabatacha"),
    ),
    CafeSet(
        "tea-master",
        "茶師の三席",
        "日本・中国・台湾の銘茶を揃える。",
        ("hon-gyokuro", "longjing", "tieguanyin"),
    ),
    CafeSet(
        "grand-afternoon",
        "夢のアフタヌーンティー",
        "特別な茶器と菓子で完成する最上段。",
        ("afternoon-tea-set", "darjeeling-first-flush", "golden-tea-set"),
    ),
    CafeSet(
        "creators-midnight",
        "創作家たちの夜更かし",
        "作曲家と文豪と詩人、その手を動かした一杯とひと皿。",
        (
            "beethoven-sixty-bean-coffee",
            "balzac-midnight-coffee",
            "dickinson-window-gingerbread",
        ),
    ),
    CafeSet(
        "recipes-in-handwriting",
        "手稿に残る甘味",
        "筆跡と逸話から、二人の菓子作りをたどる。",
        (
            "jefferson-manuscript-ice-cream",
            "dickinson-window-gingerbread",
        ),
    ),
    CafeSet(
        "unbrewable-treasures",
        "二度と淹れられない茶席",
        "飲むことより、残された来歴を味わう二つの茶葉。",
        ("last-mother-tree-da-hong-pao", "boston-harbor-tea-vial"),
    ),
    CafeSet(
        "preserved-through-time",
        "時を越えた保存食",
        "長い旅と長い歳月に耐えた、固く重い三品。",
        ("antarctic-century-fruitcake", "hardtack", "portable-soup"),
    ),
    CafeSet(
        "espresso-family",
        "エスプレッソから広がる六杯",
        "小さく濃い一杯から、ミルクとお湯で広がる定番メニュー。",
        (
            "espresso",
            "cappuccino",
            "cafe-latte",
            "americano",
            "cafe-mocha",
            "flat-white",
        ),
    ),
    CafeSet(
        "arabica-foundations",
        "アラビカ品種の系譜",
        "古い二つの系譜と、そこから広がった代表品種。",
        ("typica", "bourbon", "caturra", "mundo-novo"),
    ),
    CafeSet(
        "giant-coffee-beans",
        "大粒珈琲の競演",
        "カップの前に、豆の大きさで目を引く二つの品種。",
        ("pacamara", "maragogipe"),
    ),
    CafeSet(
        "japanese-green-tea-basics",
        "日本緑茶の基本四席",
        "蒸し方と覆い方の違いを、四つの定番で飲み比べる。",
        ("sencha", "fukamushi-sencha", "kabusecha", "matcha"),
    ),
    CafeSet(
        "tea-making-compass",
        "世界の茶づくり羅針盤",
        "烏龍茶、白茶、黒茶、紅茶を異なる産地から一席ずつ。",
        ("dong-ding-oolong", "baihao-yinzhen", "ripe-puerh", "nilgiri-orthodox"),
    ),
    CafeSet(
        "orbital-canteen-b",
        "軌道食堂Bメニュー",
        "水分とパンくずを管理した、宇宙船規格の一服。",
        ("rehydration-espresso-cube", "crumbless-scone", "orbital-tube-tiramisu"),
    ),
    CafeSet(
        "replicator-standard-menu",
        "レプリケーター標準メニュー",
        "成分表と分子データから、一杯と一皿を出力する。",
        (
            "replica-coffee-c09",
            "molecular-reconstructed-milk-tea",
            "formula-replica-apple-pie",
        ),
    ),
    CafeSet(
        "cellular-agriculture-morning",
        "細胞農業モーニング",
        "鶏も牛も豚も席を外した、未来のサンドとトースト。",
        (
            "cultured-protein-egg-sandwich",
            "precision-fermentation-cheese-toast",
            "mycelium-bacon-blt",
        ),
    ),
    CafeSet(
        "synthetic-sweets-lab",
        "合成素材の甘味試験",
        "カカオ、ゼリー、リンゴを天然原料の外側から組み立てる。",
        (
            "synthetic-cacao-cocoa",
            "nutrient-polymer-jelly",
            "formula-replica-apple-pie",
        ),
    ),
    CafeSet(
        "kansai-cafe-codewords",
        "関西の注文、通じますか",
        "明日の朝支度と、昔ながらの喫茶店で通じる短い呼び名。",
        ("tomorrows-bread", "reiko", "miko", "osaka-mixed-juice"),
    ),
    CafeSet(
        "regional-morning-border",
        "モーニング県境",
        "土地をまたぐたび、珈琲の隣に付いてくる朝食が変わる。",
        (
            "ogura-toast",
            "himeji-almond-toast",
            "gifu-chawanmushi-morning",
            "kochi-miso-soup-morning",
        ),
    ),
    CafeSet(
        "thought-it-was-a-drink",
        "飲み物だと思いました",
        "名前だけを頼りにすると、スプーンや箸が必要になる三品。",
        ("nagasaki-eating-milkshake", "okinawa-zenzai", "okaisan"),
    ),
    CafeSet(
        "bote-botebote-bukubuku-batabata",
        "ぼて・ぼてぼて・ブクブク・バタバタ",
        "似た音に油断できない、四つの土地の泡立つ茶文化。",
        ("bote-cha", "botebote-cha", "bukubuku-cha", "batabatacha"),
    ),
    CafeSet(
        "black-white-grammar-lesson-one",
        "白黒文法・第一課",
        "黒い生地と白いクリームは、重ね方だけで急に騒がしくなる。",
        ("oralalala-cookie-sandwich", "cream-left-cookie-sandwich"),
    ),
    CafeSet(
        "camera-ate-first",
        "写真が召し上がりました",
        "いちばんおいしい瞬間は、端末の写真フォルダへ保存された。",
        (
            "photo-wait-fries",
            "phone-first-parfait",
            "endless-cheese-photo-toast",
            "where-drink-ends-shake",
        ),
    ),
    CafeSet(
        "last-ones-standing",
        "最後まで残る者",
        "遠慮、太さ、重力。それぞれの事情で最後まで皿とグラスに残った。",
        ("last-cookie", "straw-defeated-tapioca", "saucer-escaped-coffee"),
    ),
    CafeSet(
        "hired-for-something-else",
        "味以外で採用",
        "音、工作、割れる瞬間。味覚以外の選考項目が強かった三品。",
        ("sound-hired-cookie", "grownup-candy-kit-plate", "glass-fruit-candy"),
    ),
    CafeSet(
        "underfoot-cafe-comedy",
        "喫茶店の足元",
        "レジ横、モーニング、電源席。見慣れた店内で拾った小さな事件。",
        (
            "checkout-financier",
            "tiny-morning-coffee",
            "outlet-seat-coffee",
            "regulars-usual",
            "menu-photo-relative-plate",
        ),
    ),
    CafeSet(
        "stone-and-fire-table",
        "石と火の食卓",
        "焚き火、石炉、土器。三つの食卓から先史時代の歩みをたどる。",
        (
            "dawn-fire-roast",
            "paleolithic-hunters-stone-plate",
            "neolithic-pottery-stew",
        ),
    ),
    CafeSet(
        "tokuhou-style-cafe",
        "特保っぽいカフェ",
        "食後、脂肪、糖、おなか。健康を気づかう六品をひと揃い。",
        (
            "post-meal-clear-tea",
            "tummy-friendly-yogurt",
            "fat-conscious-cafe-latte",
            "sugar-conscious-kanten-jelly",
            "blood-pressure-conscious-cocoa",
            "double-function-morning",
        ),
    ),
    CafeSet(
        "enchanted-cafe",
        "エンチャントされたカフェ",
        "紫の虹彩をまとった三品。どんな効果が付いたかは、味わってからのお楽しみ。",
        (
            "enchanted-apple-tart",
            "enchanted-lapis-soda",
            "enchanted-honey-toast",
        ),
    ),
    CafeSet(
        "lost-civilization-excavation",
        "失われた文明の発掘記録",
        "化石を掘り、遺跡を開き、時代に合わない星辰盤へたどり着く。地層の下に眠っていた三品。",
        (
            "fossil-strata-mille-feuille",
            "ruins-excavation-tiramisu",
            "ooparts-celestial-disk-tart",
        ),
    ),
    CafeSet(
        "portal-linked-fungal-cafe",
        "菌糸界をつなぐポータルカフェ",
        "木漏れ日の菌糸の森から、真紅と青炎が揺れるネザーへ。ポータルを挟んだ六品の幻想カフェ。",
        (
            "brown-mushroom-cream-potage",
            "red-mushroom-croque-monsieur",
            "suspicious-mushroom-stew",
            "crimson-fungus-inferno-gratin",
            "warped-fungus-soulflame-pasta",
            "nether-dual-fungus-fondue",
        ),
    ),
    CafeSet(
        "fungal-realms-drink-bar",
        "菌糸界のドリンクバー",
        "地上の香ばしさ、真紅の熱、歪んだ青炎。三つの菌糸林を一杯ずつ飲み歩く。",
        (
            "brown-mushroom-roast-latte",
            "crimson-fungus-magma-chai",
            "warped-fungus-soulflame-soda",
        ),
    ),
    CafeSet(
        "nile-riverside-temple-cafe",
        "ナイル河畔の神殿カフェ",
        "葦籠の果実と澄んだ水から始まり、神殿の青蓮、王家の黄金、星天の一杯へ。ナイル河畔をたどる十品。",
        (
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
        ),
    ),
)


def completed_set_keys(lifetime_owned_keys: set[str]) -> set[str]:
    """過去に一度でも揃えたカードから、完成セットを返す。"""
    return {
        item.key
        for item in SETS
        if set(item.required_keys).issubset(lifetime_owned_keys)
    }
