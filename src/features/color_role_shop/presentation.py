"""カラーロール交換所パネルの Discord 表示 payload を組み立てる。"""

from __future__ import annotations

from typing import Any

import discord

from src.constants import DEFAULT_EMBED_COLOR
from src.features.color_role_shop import service as color_role_service

COLOR_ROLE_OPEN_LABEL = "ロールを交換"
COLOR_ROLE_BALANCE_LABEL = "自分のXP"


def role_mention(role_id: str) -> str:
    """Discord role mention 文字列を返す。"""
    return f"<@&{role_id}>"


def item_line(item: color_role_service.ColorRoleItemView) -> str:
    """panel preview に表示する交換対象ロール 1 行を作る。"""
    label = item.label
    return f"{role_mention(item.role_id)} `{item.cost_xp:,} XP` · {label}"


def build_color_role_panel_embed(
    *,
    guild_icon_url: str | None,
    items: tuple[color_role_service.ColorRoleItemView, ...],
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
    if guild_icon_url is not None:
        embed.set_thumbnail(url=guild_icon_url)
    if not items:
        embed.add_field(
            name="交換できるロール",
            value="まだ交換対象ロールがありません。",
            inline=False,
        )
    else:
        preview = items[: color_role_service.PANEL_ITEM_PREVIEW_LIMIT]
        lines = [item_line(item) for item in preview]
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
    embed.set_footer(text="交換後のXP払い戻しはありません")
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
            ],
        }
    ]


def build_color_role_panel_message_payload(
    *,
    guild_id: str | int,
    guild_icon_url: str | None,
    items: tuple[color_role_service.ColorRoleItemView, ...],
) -> dict[str, Any]:
    """Discord REST の create message API に渡す panel message payload を作る。"""
    embed = build_color_role_panel_embed(guild_icon_url=guild_icon_url, items=items)
    return {
        "embeds": [embed.to_dict()],
        "components": build_color_role_panel_components(guild_id),
    }
