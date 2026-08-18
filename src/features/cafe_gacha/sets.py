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
)


def completed_set_keys(lifetime_owned_keys: set[str]) -> set[str]:
    """過去に一度でも揃えたカードから、完成セットを返す。"""
    return {
        item.key
        for item in SETS
        if set(item.required_keys).issubset(lifetime_owned_keys)
    }
