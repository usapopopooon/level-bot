"""重複カード用カフェメダルと棚テーマ。"""

from dataclasses import dataclass

from src.features.cafe_gacha.catalog import Rarity

MEDALS_BY_RARITY: dict[Rarity, int] = {
    "C": 1,
    "UC": 2,
    "R": 5,
    "SR": 15,
    "SSR": 50,
    "UR": 150,
    "MYTHIC": 500,
}


@dataclass(frozen=True)
class CafeCosmetic:
    key: str
    name: str
    cost_medals: int
    color: int
    decoration: str


COSMETICS: tuple[CafeCosmetic, ...] = (
    CafeCosmetic("sunny-wood", "木漏れ日の棚", 100, 0xC98B52, "🌿"),
    CafeCosmetic("midnight-cafe", "夜更かし喫茶", 250, 0x394867, "🌙"),
    CafeCosmetic("golden-cabinet", "金のカップボード", 500, 0xD6A72C, "✨"),
)
COSMETICS_BY_KEY = {item.key: item for item in COSMETICS}
