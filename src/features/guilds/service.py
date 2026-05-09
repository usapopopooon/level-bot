"""Guild + GuildSettings + ExcludedChannel CRUD.

Bot 側ライフサイクル (guild_join/remove/update) と Web/スラッシュコマンドの
両方から呼ばれる。Guild は集計の起点なので、ここが落ちると他 feature が
壊れることに注意。
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import and_, delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import ExcludedChannel, Guild, GuildSettings

# =============================================================================
# Guild + Settings
# =============================================================================


async def upsert_guild(
    session: AsyncSession,
    *,
    guild_id: str,
    name: str,
    icon_url: str | None,
    member_count: int,
) -> Guild:
    """Guild レコードを upsert する。Bot 起動時 / guild_join / guild_update で呼ぶ。"""
    stmt = select(Guild).where(Guild.guild_id == guild_id)
    result = await session.execute(stmt)
    guild = result.scalar_one_or_none()

    if guild is None:
        guild = Guild(
            guild_id=guild_id,
            name=name,
            icon_url=icon_url,
            member_count=member_count,
            is_active=True,
        )
        session.add(guild)
        await session.flush()
        # デフォルト設定も作成
        session.add(GuildSettings(guild_pk=guild.id))
    else:
        guild.name = name
        guild.icon_url = icon_url
        guild.member_count = member_count
        guild.is_active = True

    await session.commit()
    return guild


async def mark_guild_inactive(session: AsyncSession, guild_id: str) -> None:
    """Bot が kick された / guild_remove イベント時に呼ぶ。"""
    stmt = select(Guild).where(Guild.guild_id == guild_id)
    result = await session.execute(stmt)
    guild = result.scalar_one_or_none()
    if guild:
        guild.is_active = False
        await session.commit()


async def get_guild_settings(
    session: AsyncSession, guild_id: str
) -> GuildSettings | None:
    """ギルド設定を取得する (Guild の上書きされたデフォルト)。"""
    stmt = (
        select(GuildSettings)
        .join(Guild, GuildSettings.guild_pk == Guild.id)
        .where(Guild.guild_id == guild_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_active_guilds(session: AsyncSession) -> list[Guild]:
    """アクティブなギルド一覧 (Web トップページ用)。

    ``settings`` を eager-load しておかないと、async session で
    relationship アクセス時に MissingGreenlet エラーになる。
    """
    stmt = (
        select(Guild)
        .where(Guild.is_active.is_(True))
        .options(selectinload(Guild.settings))
        .order_by(Guild.name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# =============================================================================
# Excluded channels
# =============================================================================


async def is_channel_excluded(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = select(ExcludedChannel.id).where(
        and_(
            ExcludedChannel.guild_id == guild_id,
            ExcludedChannel.channel_id == channel_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_excluded_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    """除外リストに追加する。既に存在すれば False。"""
    if await is_channel_excluded(session, guild_id, channel_id):
        return False
    session.add(ExcludedChannel(guild_id=guild_id, channel_id=channel_id))
    await session.commit()
    return True


async def remove_excluded_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = delete(ExcludedChannel).where(
        and_(
            ExcludedChannel.guild_id == guild_id,
            ExcludedChannel.channel_id == channel_id,
        )
    )
    # DML の execute は CursorResult を返すが、typed stub では Result[Any] のため明示
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return (result.rowcount or 0) > 0


async def list_excluded_channels(session: AsyncSession, guild_id: str) -> list[str]:
    stmt = select(ExcludedChannel.channel_id).where(
        ExcludedChannel.guild_id == guild_id
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]
