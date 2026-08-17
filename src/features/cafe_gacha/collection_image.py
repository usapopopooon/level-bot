"""所有カードをレアリティ別に確認できるコレクション棚画像。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from src.features.cafe_gacha.catalog import (
    CARDS_BY_RARITY,
    RARITY_ORDER,
    CafeCard,
    Rarity,
    rarity_label,
)

CELL_SIZE = 160
COLUMNS = 5
ROWS = 5


@dataclass(frozen=True)
class CollectionShelfPage:
    rarity: Rarity
    page: int
    page_count: int
    card_count: int
    image: bytes


def _render_page(
    asset_dir: Path,
    counts: Mapping[str, int],
    cards: Sequence[CafeCard],
) -> bytes:
    column_count = max(1, min(COLUMNS, len(cards)))
    row_count = max(1, min(ROWS, (len(cards) + column_count - 1) // column_count))
    canvas = Image.new(
        "RGB", (CELL_SIZE * column_count, CELL_SIZE * row_count), "#251a16"
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    with Image.open(asset_dir / "card-back.jpg") as card_back_source:
        card_back = card_back_source.convert("RGB")

    for index in range(column_count * row_count):
        x = index % column_count * CELL_SIZE
        y = index // column_count * CELL_SIZE
        if index >= len(cards):
            draw.rectangle(
                (x + 3, y + 3, x + CELL_SIZE - 3, y + CELL_SIZE - 3),
                outline="#4a342a",
                width=2,
            )
            continue

        card = cards[index]
        count = max(0, counts.get(card.key, 0))
        if count:
            with Image.open(asset_dir / card.image_filename) as source_image:
                source = source_image.convert("RGB")
        else:
            source = card_back.copy()
        tile = ImageOps.fit(source, (CELL_SIZE, CELL_SIZE))
        if not count:
            tile = ImageEnhance.Brightness(tile).enhance(0.38)
        canvas.paste(tile, (x, y))
        draw.rectangle((x + 4, y + 4, x + 58, y + 32), fill="#17100dcc")
        draw.text((x + 10, y + 8), rarity_label(card.rarity), font=font, fill="white")
        badge = "-" if count == 0 else f"x{count}"
        draw.rectangle(
            (
                x + CELL_SIZE - 58,
                y + CELL_SIZE - 34,
                x + CELL_SIZE - 4,
                y + CELL_SIZE - 4,
            ),
            fill="#17100dcc",
        )
        draw.text(
            (x + CELL_SIZE - 51, y + CELL_SIZE - 30),
            badge,
            font=font,
            fill="white",
        )

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()


def render_collection_shelves(
    asset_dir: Path, counts: Mapping[str, int]
) -> tuple[CollectionShelfPage, ...]:
    """Discordの添付上限内で、N〜SSRの5枚の棚画像を生成する。"""
    pages: list[CollectionShelfPage] = []
    page_size = COLUMNS * ROWS
    for rarity in RARITY_ORDER:
        rarity_cards = CARDS_BY_RARITY[rarity]
        chunks = tuple(
            rarity_cards[start : start + page_size]
            for start in range(0, len(rarity_cards), page_size)
        )
        for page, cards in enumerate(chunks, start=1):
            pages.append(
                CollectionShelfPage(
                    rarity=rarity,
                    page=page,
                    page_count=len(chunks),
                    card_count=len(cards),
                    image=_render_page(asset_dir, counts, cards),
                )
            )
    return tuple(pages)
