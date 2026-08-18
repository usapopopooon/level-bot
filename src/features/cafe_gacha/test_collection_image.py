from io import BytesIO
from pathlib import Path

from PIL import Image

from src.features.cafe_gacha.collection_image import (
    CELL_SIZE,
    COLUMNS,
    ROWS,
    render_collection_shelves,
)


def test_render_collection_shelves_pages_large_rarity_groups() -> None:
    asset_dir = Path(__file__).parent / "assets"
    pages = render_collection_shelves(asset_dir, {"spent-tea": 2})

    assert [page.rarity for page in pages] == [
        "C",
        "C",
        "C",
        "UC",
        "UC",
        "R",
        "R",
        "SR",
        "SR",
        "SSR",
    ]
    assert sum(page.card_count for page in pages) == 184
    for page in pages:
        with Image.open(BytesIO(page.image)) as image:
            expected_columns = max(
                1,
                min(COLUMNS, page.card_count),
            )
            expected_rows = max(
                1,
                min(
                    ROWS,
                    (page.card_count + expected_columns - 1) // expected_columns,
                ),
            )
            assert image.size == (
                CELL_SIZE * expected_columns,
                CELL_SIZE * expected_rows,
            )
            assert image.format == "JPEG"

    assert [(page.page, page.page_count) for page in pages[:3]] == [
        (1, 3),
        (2, 3),
        (3, 3),
    ]
    ssr_page = next(page for page in pages if page.rarity == "SSR")
    with Image.open(BytesIO(ssr_page.image)) as image:
        assert image.size == (CELL_SIZE * 5, CELL_SIZE * 2)
