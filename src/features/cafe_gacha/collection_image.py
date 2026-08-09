"""所有カードを一目で確認できるコレクション棚画像。"""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from src.features.cafe_gacha.catalog import CARDS

CELL_SIZE = 160
COLUMNS = 5
ROWS = 3


def render_collection_shelf(asset_dir: Path, counts: Mapping[str, int]) -> bytes:
    canvas = Image.new("RGB", (CELL_SIZE * COLUMNS, CELL_SIZE * ROWS), "#251a16")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    card_back = Image.open(asset_dir / "card-back.jpg").convert("RGB")

    for index, card in enumerate(CARDS):
        count = max(0, counts.get(card.key, 0))
        source = (
            Image.open(asset_dir / card.image_filename).convert("RGB")
            if count
            else card_back.copy()
        )
        tile = ImageOps.fit(source, (CELL_SIZE, CELL_SIZE))
        if not count:
            tile = ImageEnhance.Brightness(tile).enhance(0.38)
        x = index % COLUMNS * CELL_SIZE
        y = index // COLUMNS * CELL_SIZE
        canvas.paste(tile, (x, y))
        draw.rectangle((x + 4, y + 4, x + 58, y + 32), fill="#17100dcc")
        draw.text((x + 10, y + 8), card.rarity, font=font, fill="white")
        badge = "—" if count == 0 else f"×{count}"
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
