"""Tests for image VC heatmaps."""

from io import BytesIO

from PIL import Image

from src.features.stats.heatmap_image import render_hourly_activity_heatmap_table_png
from src.features.stats.service import HourlyActivityCell


def _cells(entries: dict[tuple[int, int], int]) -> list[HourlyActivityCell]:
    return [
        HourlyActivityCell(
            weekday=weekday,
            hour=hour,
            voice_seconds=entries.get((weekday, hour), 0),
            active_users=1 if entries.get((weekday, hour), 0) > 0 else 0,
            intensity_percent=0,
        )
        for weekday in range(7)
        for hour in range(24)
    ]


def _alpha_at(image: Image.Image, x: int, y: int) -> int:
    pixel = image.getpixel((x, y))
    assert isinstance(pixel, tuple)
    return pixel[3]


def test_render_hourly_activity_heatmap_table_png_returns_png() -> None:
    image = render_hourly_activity_heatmap_table_png(
        cells=_cells(
            {
                (0, 18): 3600,
                (1, 21): 2400,
                (5, 12): 1200,
            }
        ),
    )

    data = image.getvalue()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 1000

    rendered = Image.open(BytesIO(data)).convert("RGBA")
    assert rendered.mode == "RGBA"
    assert _alpha_at(rendered, 0, 0) == 0

    visible_xs = [
        x
        for y in range(rendered.height)
        for x in range(rendered.width)
        if _alpha_at(rendered, x, y) > 0
    ]
    assert abs(min(visible_xs) - (rendered.width - 1 - max(visible_xs))) <= 1
