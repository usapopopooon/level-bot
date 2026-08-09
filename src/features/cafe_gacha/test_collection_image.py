from io import BytesIO
from pathlib import Path

from PIL import Image

from src.features.cafe_gacha.collection_image import (
    CELL_SIZE,
    COLUMNS,
    ROWS,
    render_collection_shelf,
)


def test_render_collection_shelf_has_stable_dimensions() -> None:
    asset_dir = Path(__file__).parent / "assets"
    data = render_collection_shelf(asset_dir, {"spent-tea": 2})

    with Image.open(BytesIO(data)) as image:
        assert image.size == (CELL_SIZE * COLUMNS, CELL_SIZE * ROWS)
        assert image.format == "JPEG"
