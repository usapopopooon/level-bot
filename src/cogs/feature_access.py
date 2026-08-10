"""Discord UI から機能別利用ロールを検査する共通境界。"""

from __future__ import annotations

import discord

from src.database.engine import async_session
from src.features.feature_access import service


async def _send_ephemeral(
    interaction: discord.Interaction,
    content: str,
) -> None:
    allowed_mentions = discord.AllowedMentions.none()
    if interaction.response.is_done():
        await interaction.followup.send(
            content,
            ephemeral=True,
            allowed_mentions=allowed_mentions,
        )
    else:
        await interaction.response.send_message(
            content,
            ephemeral=True,
            allowed_mentions=allowed_mentions,
        )


def _member_role_ids(interaction: discord.Interaction) -> set[str]:
    member: discord.Member | None = None
    if isinstance(interaction.user, discord.Member):
        member = interaction.user
    elif interaction.guild is not None:
        member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        return set()
    return {str(role.id) for role in member.roles}


def format_access_roles(role_ids: tuple[str, ...]) -> str:
    """Discord の本文上限を超えない範囲で許可ロールを表示する。"""
    visible = role_ids[:20]
    mentions = "、".join(f"<@&{role_id}>" for role_id in visible)
    if len(role_ids) > len(visible):
        mentions += f"、ほか {len(role_ids) - len(visible)}件"
    return mentions


async def ensure_feature_access(
    interaction: discord.Interaction,
    *,
    guild_id: int | str,
    feature: service.FeatureKey,
) -> bool:
    """現在の操作に利用資格があれば True、なければ非公開で理由を返す。"""
    expected_guild_id = int(guild_id)
    if interaction.guild is None or interaction.guild.id != expected_guild_id:
        await _send_ephemeral(interaction, "このサーバーでは利用できません。")
        return False

    can_manage_guild = (
        interaction.permissions.administrator or interaction.permissions.manage_guild
    )
    async with async_session() as session:
        allowed_role_ids = await service.list_access_role_ids(
            session,
            guild_id=str(expected_guild_id),
            feature=feature,
        )
    if service.member_has_access(
        allowed_role_ids=allowed_role_ids,
        member_role_ids=_member_role_ids(interaction),
        can_manage_guild=can_manage_guild,
    ):
        return True

    await _send_ephemeral(
        interaction,
        "この機能を利用できるロールがありません。\n"
        f"利用可能なロール: {format_access_roles(allowed_role_ids)}",
    )
    return False
