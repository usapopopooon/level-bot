from io import BytesIO
from pathlib import Path

from PIL import Image

from src.features.cafe_gacha.catalog import CARDS_BY_RARITY, RARITY_ORDER
from src.features.cafe_gacha.collection_image import (
    CELL_SIZE,
    COLUMNS,
    ROWS,
    render_collection_shelves,
)


def test_render_collection_shelves_has_one_stable_page_per_rarity() -> None:
    asset_dir = Path(__file__).parent / "assets"
    pages = render_collection_shelves(asset_dir, {"spent-tea": 2})

    assert [page.rarity for page in pages] == list(RARITY_ORDER)
    assert sum(page.card_count for page in pages) == 100
    for page in pages:
        with Image.open(BytesIO(page.image)) as image:
            expected_columns = max(
                1,
                min(COLUMNS, len(CARDS_BY_RARITY[page.rarity])),
            )
            expected_rows = max(
                1,
                min(
                    ROWS,
                    (len(CARDS_BY_RARITY[page.rarity]) + expected_columns - 1)
                    // expected_columns,
                ),
            )
            assert image.size == (
                CELL_SIZE * expected_columns,
                CELL_SIZE * expected_rows,
            )
            assert image.format == "JPEG"

    ssr_page = next(page for page in pages if page.rarity == "SSR")
    with Image.open(BytesIO(ssr_page.image)) as image:
        assert image.size == (CELL_SIZE * 4, CELL_SIZE)
