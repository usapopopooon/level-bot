"""PNG rendering for Discord-friendly activity heatmaps."""

from __future__ import annotations

import importlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from src.features.stats.service import HourlyActivityCell
from src.utils import format_seconds

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

BACKGROUND = (13, 17, 23)
PANEL = (20, 27, 34)
GRID_LINE = (43, 53, 65)
TEXT = (232, 238, 247)
MUTED = (139, 152, 166)
ACCENT = (125, 211, 199)

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
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
    candidates: tuple[str, ...] = FONT_CANDIDATES
    if bold:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *FONT_CANDIDATES,
        )
    for path in candidates:
        if Path(path).exists():
            return image_font.truetype(path, size)
    return image_font.load_default()


def _text_size(draw: Any, text: str, font: Any) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _lerp(start: int, end: int, ratio: float) -> int:
    return round(start + (end - start) * ratio)


def _cell_color(intensity: int) -> tuple[int, int, int]:
    if intensity <= 0:
        return (21, 27, 34)
    ratio = max(0.0, min(intensity / 100, 1.0))
    return (
        _lerp(22, 125, ratio),
        _lerp(65, 211, ratio),
        _lerp(67, 199, ratio),
    )


def _rounded_rectangle(
    draw: Any,
    xy: tuple[int, int, int, int],
    *,
    radius: int,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def render_hourly_activity_heatmap_png(
    *,
    guild_name: str,
    days: int,
    cells: list[HourlyActivityCell],
    generated_at: datetime,
) -> BytesIO:
    """Render a weekday x hour voice activity heatmap as an in-memory PNG."""
    Image, ImageDraw, ImageFont = _load_pillow()

    width = 1280
    height = 960
    margin = 48
    chart_x = 118
    chart_y = 184
    cell_w = 154
    cell_h = 22
    gap = 5

    img = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(img)

    title_font = _font(ImageFont, 42, bold=True)
    subtitle_font = _font(ImageFont, 20)
    label_font = _font(ImageFont, 18, bold=True)
    small_font = _font(ImageFont, 15)
    peak_font = _font(ImageFont, 22, bold=True)

    _rounded_rectangle(
        draw,
        (margin, 36, width - margin, height - 36),
        radius=28,
        fill=PANEL,
        outline=(35, 45, 57),
        width=2,
    )

    title = "Voice Activity Heatmap"
    draw.text((82, 72), title, fill=TEXT, font=title_font)
    subtitle = f"{guild_name} / last {days} days / bots excluded"
    draw.text((84, 126), subtitle, fill=MUTED, font=subtitle_font)

    by_key = {(cell.weekday, cell.hour): cell for cell in cells}
    peak = max(cells, key=lambda cell: cell.voice_seconds, default=None)
    if peak and peak.voice_seconds > 0:
        peak_label = f"Peak  {WEEKDAYS[peak.weekday]} {peak.hour:02d}:00"
        peak_value = format_seconds(peak.voice_seconds)
        box = (width - 380, 72, width - 86, 138)
        _rounded_rectangle(
            draw,
            box,
            radius=18,
            fill=(28, 44, 48),
            outline=(47, 89, 87),
            width=2,
        )
        draw.text((box[0] + 20, box[1] + 12), peak_label, fill=ACCENT, font=small_font)
        draw.text((box[0] + 20, box[1] + 34), peak_value, fill=TEXT, font=peak_font)

    for weekday, label in enumerate(WEEKDAYS):
        x = chart_x + weekday * (cell_w + gap)
        text_w, _ = _text_size(draw, label, label_font)
        draw.text(
            (x + (cell_w - text_w) / 2, chart_y - 34),
            label,
            fill=MUTED,
            font=label_font,
        )

    for hour in range(24):
        y = chart_y + hour * (cell_h + gap)
        hour_label = f"{hour:02d}"
        _, text_h = _text_size(draw, hour_label, small_font)
        draw.text(
            (78, y + (cell_h - text_h) / 2),
            hour_label,
            fill=MUTED,
            font=small_font,
        )

        for weekday in range(7):
            x = chart_x + weekday * (cell_w + gap)
            cell = by_key.get((weekday, hour))
            intensity = cell.intensity_percent if cell else 0
            _rounded_rectangle(
                draw,
                (x, y, x + cell_w, y + cell_h),
                radius=6,
                fill=_cell_color(intensity),
                outline=GRID_LINE,
            )

    legend_x = 84
    legend_y = height - 92
    draw.text((legend_x, legend_y), "Less", fill=MUTED, font=small_font)
    for index, intensity in enumerate((0, 25, 50, 75, 100)):
        x = legend_x + 52 + index * 38
        _rounded_rectangle(
            draw,
            (x, legend_y - 2, x + 28, legend_y + 20),
            radius=5,
            fill=_cell_color(intensity),
            outline=GRID_LINE,
        )
    draw.text((legend_x + 252, legend_y), "More", fill=MUTED, font=small_font)

    footer = f"Generated {generated_at:%Y-%m-%d %H:%M UTC}"
    footer_w, _ = _text_size(draw, footer, small_font)
    draw.text(
        (width - margin - footer_w, height - 92),
        footer,
        fill=MUTED,
        font=small_font,
    )

    output = BytesIO()
    img.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
