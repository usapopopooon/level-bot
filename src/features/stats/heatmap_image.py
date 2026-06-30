"""Simple PNG rendering for Discord-friendly VC activity heatmaps."""

from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path
from typing import Any

from src.features.stats.heatmap_text import (
    BUCKET_HOURS,
    WEEKDAYS_JA,
    bucket_hourly_activity_heatmap_voice_seconds,
    hourly_activity_heatmap_level,
)
from src.features.stats.service import HourlyActivityCell

BACKGROUND = (0, 0, 0, 0)
TEXT = (64, 53, 46, 245)
MUTED = (118, 96, 82, 235)
TEXT_STROKE = (255, 255, 255, 210)

HEAT_COLORS = (
    (204, 45, 55, 24),
    (204, 45, 55, 64),
    (204, 45, 55, 112),
    (204, 45, 55, 168),
    (204, 45, 55, 224),
)

FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    *FONT_CANDIDATES,
)


def _load_pillow() -> tuple[Any, Any, Any]:
    try:
        image = importlib.import_module("PIL.Image")
        image_draw = importlib.import_module("PIL.ImageDraw")
        image_font = importlib.import_module("PIL.ImageFont")
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        msg = "Pillow is required to render heatmap images."
        raise RuntimeError(msg) from exc
    return image, image_draw, image_font


def _font(image_font: Any, size: int, *, bold: bool = False) -> Any:
    candidates = BOLD_FONT_CANDIDATES if bold else FONT_CANDIDATES
    for path in candidates:
        if Path(path).exists():
            return image_font.truetype(path, size)
    return image_font.load_default()


def _text_size(draw: Any, text: str, font: Any) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _draw_centered_text(
    draw: Any,
    xy: tuple[int, int, int, int],
    text: str,
    *,
    font: Any,
    fill: tuple[int, int, int, int],
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    left, top, right, bottom = xy
    text_w, text_h = _text_size(draw, text, font)
    x = left + (right - left - text_w) / 2
    y = top + (bottom - top - text_h) / 2 - 1
    draw.text(
        (x, y),
        text,
        fill=fill,
        font=font,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def render_hourly_activity_heatmap_table_png(
    *,
    cells: list[HourlyActivityCell],
) -> BytesIO:
    """Render a compact weekday x 3-hour VC heatmap table as PNG."""
    Image, ImageDraw, ImageFont = _load_pillow()

    width = 1040
    height = 600
    label_w = 78
    cell_w = 96
    cell_h = 54
    gap = 8
    table_x = 69
    table_y = 42

    img = Image.new("RGBA", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(img)

    label_font = _font(ImageFont, 24, bold=True)
    small_font = _font(ImageFont, 20)
    legend_font = _font(ImageFont, 18, bold=True)

    for column, hour in enumerate(BUCKET_HOURS):
        x = table_x + label_w + column * (cell_w + gap)
        _draw_centered_text(
            draw,
            (x, table_y, x + cell_w, table_y + 36),
            str(hour),
            font=small_font,
            fill=MUTED,
            stroke_width=2,
            stroke_fill=TEXT_STROKE,
        )

    buckets = bucket_hourly_activity_heatmap_voice_seconds(cells)
    max_voice_seconds = max(buckets.values(), default=0)

    for weekday, label in enumerate(WEEKDAYS_JA):
        y = table_y + 44 + weekday * (cell_h + gap)
        _draw_centered_text(
            draw,
            (table_x, y, table_x + label_w - 10, y + cell_h),
            label,
            font=label_font,
            fill=TEXT,
            stroke_width=2,
            stroke_fill=TEXT_STROKE,
        )

        for column, hour in enumerate(BUCKET_HOURS):
            x = table_x + label_w + column * (cell_w + gap)
            voice_seconds = buckets.get((weekday, hour), 0)
            level = hourly_activity_heatmap_level(voice_seconds, max_voice_seconds)
            draw.rounded_rectangle(
                (x, y, x + cell_w, y + cell_h),
                radius=8,
                fill=HEAT_COLORS[level],
            )

    legend_y = height - 60
    draw.text(
        (table_x, legend_y + 7),
        "少ない",
        fill=MUTED,
        font=legend_font,
        stroke_width=2,
        stroke_fill=TEXT_STROKE,
    )
    for level, color in enumerate(HEAT_COLORS):
        x = table_x + 76 + level * 44
        draw.rounded_rectangle(
            (x, legend_y, x + 32, legend_y + 32),
            radius=7,
            fill=color,
        )
    draw.text(
        (table_x + 308, legend_y + 7),
        "多い",
        fill=MUTED,
        font=legend_font,
        stroke_width=2,
        stroke_fill=TEXT_STROKE,
    )

    output = BytesIO()
    img.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
