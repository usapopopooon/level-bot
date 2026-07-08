"""カラーロール交換所パネルの Discord 表示 payload を組み立てる。"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import discord

from src.constants import DEFAULT_EMBED_COLOR
from src.features.color_role_shop import service as color_role_service

COLOR_ROLE_OPEN_LABEL = "ロールを交換"
COLOR_ROLE_BALANCE_LABEL = "自分のXP"
COLOR_ROLE_CLEAR_LABEL = "ロールを外す"
COLOR_ROLE_SAMPLE_IMAGE_FILENAME = "color-role-samples.png"
COLOR_ROLE_SAMPLE_ATTACHMENT_URL = f"attachment://{COLOR_ROLE_SAMPLE_IMAGE_FILENAME}"

_TRANSPARENT = (0, 0, 0, 0)
_DEFAULT_ROLE_COLOR = (148, 163, 184, 92)
_TEXT_SHADOW = (15, 23, 42, 185)
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


@dataclass(frozen=True)
class PanelAttachment:
    """Discord message に添付する小さなバイナリファイル。"""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class ColorRolePanelMessage:
    """REST 投稿用の message payload と添付ファイルをまとめた値。"""

    payload: dict[str, Any]
    attachments: tuple[PanelAttachment, ...]


def role_mention(role_id: str) -> str:
    """Discord role mention 文字列を返す。"""
    return f"<@&{role_id}>"


def _role_color_value(color: int | None) -> int | None:
    if color is None or color <= 0:
        return None
    return max(0, min(0xFFFFFF, int(color)))


def item_line(
    item: color_role_service.ColorRoleItemView,
    *,
    sample_number: int | None = None,
) -> str:
    """panel preview に表示する交換対象ロール 1 行を作る。"""
    prefix = f"`{sample_number:02}` " if sample_number is not None else ""
    label = item.label
    return (
        f"{prefix}{role_mention(item.role_id)} `{item.cost_xp:,} XP` · {label}"
    )


def _load_pillow() -> tuple[Any, Any, Any]:
    try:
        image = importlib.import_module("PIL.Image")
        image_draw = importlib.import_module("PIL.ImageDraw")
        image_font = importlib.import_module("PIL.ImageFont")
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        msg = "Pillow is required to render color role sample images."
        raise RuntimeError(msg) from exc
    return image, image_draw, image_font


def _font(image_font: Any, size: int) -> Any:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return image_font.truetype(path, size)
    return image_font.load_default()


def _text_size(draw: Any, text: str, font: Any) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _fit_text(draw: Any, text: str, font: Any, max_width: int) -> str:
    """PNG 内の表示名を幅に収まるよう省略する。"""
    if _text_size(draw, text, font)[0] <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed:
        candidate = f"{trimmed}{ellipsis}"
        if _text_size(draw, candidate, font)[0] <= max_width:
            return candidate
        trimmed = trimmed[:-1]
    return ellipsis


def _role_color_fill(color: int | None) -> tuple[int, int, int, int]:
    value = _role_color_value(color)
    if value is None:
        return _DEFAULT_ROLE_COLOR
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, 255)


def build_color_role_sample_attachment(
    items: tuple[color_role_service.ColorRoleItemView, ...],
) -> PanelAttachment | None:
    """panel に添える透明 PNG の色見本を作る。"""
    preview = items[: color_role_service.PANEL_ITEM_PREVIEW_LIMIT]
    if not preview:
        return None

    Image, ImageDraw, ImageFont = _load_pillow()
    columns = 2
    card_w = 430
    card_h = 86
    swatch_w = 72
    gap = 18
    padding = 24
    rows = (len(preview) + columns - 1) // columns
    width = padding * 2 + columns * card_w + (columns - 1) * gap
    height = padding * 2 + rows * card_h + (rows - 1) * gap

    image = Image.new("RGBA", (width, height), _TRANSPARENT)
    draw = ImageDraw.Draw(image)
    title_font = _font(ImageFont, 23)
    detail_font = _font(ImageFont, 18)
    number_font = _font(ImageFont, 22)

    for index, item in enumerate(preview, start=1):
        row = (index - 1) // columns
        column = (index - 1) % columns
        left = padding + column * (card_w + gap)
        top = padding + row * (card_h + gap)
        card_box = (left, top, left + card_w, top + card_h)
        swatch_box = (
            left,
            top,
            left + swatch_w,
            top + card_h,
        )
        fill = _role_color_fill(item.color)
        draw.rounded_rectangle(
            card_box,
            radius=14,
            fill=(15, 23, 42, 38),
        )
        draw.rounded_rectangle(
            swatch_box,
            radius=14,
            fill=fill,
        )

        number = f"{index:02}"
        number_w, number_h = _text_size(draw, number, number_font)
        number_x = left + (swatch_w - number_w) / 2
        number_y = top + (card_h - number_h) / 2 - 1
        draw.text(
            (number_x, number_y),
            number,
            fill=(255, 255, 255, 245),
            font=number_font,
        )

        text_left = left + swatch_w + 16
        text_width = card_w - swatch_w - 32
        label = _fit_text(draw, item.label, title_font, text_width)
        detail = f"必要XP {item.cost_xp:,}"
        detail = _fit_text(draw, detail, detail_font, text_width)
        draw.text(
            (text_left, top + 15),
            label,
            fill=(248, 250, 252, 245),
            font=title_font,
            stroke_width=2,
            stroke_fill=_TEXT_SHADOW,
        )
        draw.text(
            (text_left, top + 49),
            detail,
            fill=(203, 213, 225, 235),
            font=detail_font,
            stroke_width=2,
            stroke_fill=_TEXT_SHADOW,
        )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return PanelAttachment(
        filename=COLOR_ROLE_SAMPLE_IMAGE_FILENAME,
        content_type="image/png",
        data=output.getvalue(),
    )


def build_color_role_panel_embed(
    *,
    items: tuple[color_role_service.ColorRoleItemView, ...],
    include_sample_image: bool = True,
) -> discord.Embed:
    """公開チャンネルに置くカラーロール交換所パネル embed を作る。"""
    embed = discord.Embed(
        title="カラーロール交換所",
        description=(
            "活動で貯めた XP を使ってロールを交換できます。\n"
            "色を変えるたびに必要XPを消費し、交換操作と残高確認は本人にだけ表示されます。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    if not items:
        embed.add_field(
            name="交換できるロール",
            value="まだ交換対象ロールがありません。",
            inline=False,
        )
    else:
        preview = items[: color_role_service.PANEL_ITEM_PREVIEW_LIMIT]
        lines = [
            item_line(item, sample_number=index)
            for index, item in enumerate(preview, start=1)
        ]
        if len(items) > len(preview):
            lines.append(f"ほか {len(items) - len(preview)} 件")
        embed.add_field(
            name="交換できるロール",
            value="\n".join(lines),
            inline=False,
        )
    embed.add_field(
        name="使い方",
        value="`ロールを交換` → ロール選択 → 内容確認 → `交換する`",
        inline=False,
    )
    embed.add_field(
        name="切り替え",
        value="新しいロールを交換すると、他の交換ロールは外れます。",
        inline=False,
    )
    embed.add_field(
        name="外す",
        value="`ロールを外す` で現在のカラーロールだけを外せます。XP は戻りません。",
        inline=False,
    )
    embed.set_footer(text="交換後のXP払い戻しはありません")
    if include_sample_image and items:
        embed.set_image(url=COLOR_ROLE_SAMPLE_ATTACHMENT_URL)
    return embed


def build_color_role_panel_components(guild_id: str | int) -> list[dict[str, Any]]:
    """永続 button を Discord REST へ渡せる component payload として作る。"""
    guild_id_text = str(guild_id)
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 1,
                    "disabled": False,
                    "label": COLOR_ROLE_OPEN_LABEL,
                    "custom_id": f"level:color-role:open:{guild_id_text}",
                },
                {
                    "type": 2,
                    "style": 2,
                    "disabled": False,
                    "label": COLOR_ROLE_BALANCE_LABEL,
                    "custom_id": f"level:color-role:balance:{guild_id_text}",
                },
                {
                    "type": 2,
                    "style": 4,
                    "disabled": False,
                    "label": COLOR_ROLE_CLEAR_LABEL,
                    "custom_id": f"level:color-role:clear:{guild_id_text}",
                },
            ],
        }
    ]


def build_color_role_panel_message(
    *,
    guild_id: str | int,
    items: tuple[color_role_service.ColorRoleItemView, ...],
) -> ColorRolePanelMessage:
    """Discord REST 投稿に必要な JSON payload と添付 PNG をまとめて作る。"""
    attachment = build_color_role_sample_attachment(items)
    embed = build_color_role_panel_embed(
        items=items,
        include_sample_image=attachment is not None,
    )
    payload = {
        "embeds": [embed.to_dict()],
        "components": build_color_role_panel_components(guild_id),
        **(
            {
                "attachments": [
                    {
                        "id": 0,
                        "filename": attachment.filename,
                    }
                ]
            }
            if attachment is not None
            else {}
        ),
    }
    attachments = (attachment,) if attachment is not None else ()
    return ColorRolePanelMessage(payload=payload, attachments=attachments)
