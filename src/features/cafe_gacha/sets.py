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
)


def completed_set_keys(lifetime_owned_keys: set[str]) -> set[str]:
    """過去に一度でも揃えたカードから、完成セットを返す。"""
    return {
        item.key
        for item in SETS
        if set(item.required_keys).issubset(lifetime_owned_keys)
    }
