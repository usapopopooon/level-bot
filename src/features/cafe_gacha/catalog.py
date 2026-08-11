"""カフェガチャの固定カタログと抽選テーブル。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type Rarity = Literal["C", "UC", "R", "SR", "SSR"]

PAID_DRAW_COST_XP = 20
MAX_HOURLY_DRAWS = 10
TOTAL_WEIGHT = 10_000
DRAW_REWARD_XP_BY_RARITY: dict[Rarity, int] = {
    "C": 25,
    "UC": 30,
    "R": 50,
    "SR": 100,
    "SSR": 300,
}
RARITY_LABELS: dict[str, str] = {
    "C": "N",
    "UC": "HN",
}


def rarity_label(rarity: str) -> str:
    return RARITY_LABELS.get(rarity, rarity)


@dataclass(frozen=True)
class CafeCard:
    key: str
    name: str
    rarity: Rarity
    weight: int
    description: str
    image_filename: str

    @property
    def exchange_xp(self) -> int:
        """重複交換時も獲得時と同額のXPを返す。"""
        return self.draw_reward_xp

    @property
    def draw_reward_xp(self) -> int:
        return DRAW_REWARD_XP_BY_RARITY[self.rarity]


CARDS: tuple[CafeCard, ...] = (
    CafeCard(
        "spent-tea",
        "出がらし",
        "C",
        1560,
        "まだ一杯くらいなら、たぶん。",
        "spent-tea.jpg",
    ),
    CafeCard(
        "cold-black-tea",
        "冷めた紅茶",
        "C",
        1460,
        "話に夢中だった証拠の一杯。",
        "cold-black-tea.jpg",
    ),
    CafeCard(
        "k-pan",
        "Kブロート",
        "C",
        1360,
        "ジャガイモでかさ増しされた、戦時下の代用パン。",
        "k-pan.jpg",
    ),
    CafeCard(
        "sunflower-coffee",
        "ひまわりコーヒー",
        "C",
        1260,
        "種を焙煎した、珈琲によく似た香ばしい飲み物。",
        "sunflower-coffee.jpg",
    ),
    CafeCard(
        "acorn-coffee",
        "どんぐりコーヒー",
        "C",
        1160,
        "森の実から生まれた素朴な代用珈琲。",
        "acorn-coffee.jpg",
    ),
    CafeCard(
        "barley-chicory-coffee",
        "麦とチコリの代用珈琲",
        "UC",
        900,
        "麦の香ばしさとチコリのほろ苦さ。",
        "barley-chicory-coffee.jpg",
    ),
    CafeCard(
        "genmaicha",
        "玄米茶",
        "UC",
        780,
        "湯気の向こうに、炒り米のやさしい香り。",
        "genmaicha.jpg",
    ),
    CafeCard(
        "scone",
        "スコーン",
        "UC",
        620,
        "狼藉を働かず、まずはクロテッドクリームを。",
        "scone.jpg",
    ),
    CafeCard(
        "earl-grey",
        "アールグレイ",
        "R",
        270,
        "ベルガモットが華やぐ午後の定番。",
        "earl-grey.jpg",
    ),
    CafeCard(
        "hojicha-latte",
        "ほうじ茶ラテ",
        "R",
        230,
        "焙じ香とミルクがほどける夜の一杯。",
        "hojicha-latte.jpg",
    ),
    CafeCard(
        "house-blend",
        "店主の特製ブレンド",
        "R",
        200,
        "配合は秘密。今日の気分だけが隠し味。",
        "house-blend.jpg",
    ),
    CafeCard(
        "blooming-tea",
        "工芸茶",
        "SR",
        95,
        "ポットの中で花ひらく、小さな茶会。",
        "blooming-tea.jpg",
    ),
    CafeCard(
        "afternoon-tea-set",
        "アフタヌーンティーセット",
        "SR",
        75,
        "三段重ねに甘味と会話を盛りつけて。",
        "afternoon-tea-set.jpg",
    ),
    CafeCard(
        "legendary-tea-leaves",
        "幻の茶葉",
        "SSR",
        18,
        "店主でさえ滅多に封を切らない秘蔵品。",
        "legendary-tea-leaves.jpg",
    ),
    CafeCard(
        "golden-tea-set",
        "黄金のティーセット",
        "SSR",
        12,
        "茶会そのものが伝説になる眩い一式。",
        "golden-tea-set.jpg",
    ),
)
CARDS_BY_KEY = {card.key: card for card in CARDS}

if sum(card.weight for card in CARDS) != TOTAL_WEIGHT:
    raise RuntimeError("cafe gacha weights must total 10,000")


def select_card(value: int) -> CafeCard:
    """0..9999 の値を固定抽選表へ写像する。境界テスト用の純粋関数。"""
    if not 0 <= value < TOTAL_WEIGHT:
        msg = f"value must be between 0 and {TOTAL_WEIGHT - 1}"
        raise ValueError(msg)
    cursor = 0
    for card in CARDS:
        cursor += card.weight
        if value < cursor:
            return card
    raise AssertionError("unreachable catalog boundary")
