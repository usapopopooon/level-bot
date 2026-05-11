"""User / channel meta upsert + lookup helpers.

Discord 表示名・アバターを毎回 API で叩かないように、最近の集計対象を
キャッシュしておく。集計テーブル (``daily_stats``) や進行中ボイス
(``voice_sessions``) は ID しか持たないので、表示用は必ずここを引く。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ChannelMeta, UserMeta

# PG の bind parameter 上限 (32k 程度) を超えないよう、bulk 時はチャンクで送る
_BULK_UPSERT_CHUNK_SIZE = 500


async def upsert_user_meta(
    session: AsyncSession,
    *,
    user_id: str,
    display_name: str,
    avatar_url: str | None,
    is_bot: bool,
) -> None:
    stmt = pg_insert(UserMeta).values(
        user_id=user_id,
        display_name=display_name,
        avatar_url=avatar_url,
        is_bot=is_bot,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserMeta.user_id],
        set_={
            "display_name": display_name,
            "avatar_url": avatar_url,
            "is_bot": is_bot,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def upsert_channel_meta(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    name: str,
    channel_type: str,
) -> None:
    stmt = pg_insert(ChannelMeta).values(
        guild_id=guild_id,
        channel_id=channel_id,
        name=name,
        channel_type=channel_type,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_channel_meta",
        set_={
            "name": name,
            "channel_type": channel_type,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def bulk_upsert_user_meta(
    session: AsyncSession,
    members: Iterable[dict[str, Any]],
) -> int:
    """複数メンバーの meta を 1 INSERT (chunk 分割) で upsert する。

    起動時バックフィル用。各 dict は ``user_id / display_name / avatar_url / is_bot``。
    """
    values = list(members)
    if not values:
        return 0
    now = datetime.now(UTC)
    for i in range(0, len(values), _BULK_UPSERT_CHUNK_SIZE):
        chunk = values[i : i + _BULK_UPSERT_CHUNK_SIZE]
        stmt = pg_insert(UserMeta).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserMeta.user_id],
            set_={
                "display_name": stmt.excluded.display_name,
                "avatar_url": stmt.excluded.avatar_url,
                "is_bot": stmt.excluded.is_bot,
                "updated_at": now,
            },
        )
        await session.execute(stmt)
    await session.commit()
    return len(values)


async def bulk_upsert_channel_meta(
    session: AsyncSession,
    channels: Iterable[dict[str, Any]],
) -> int:
    """複数チャンネルの meta を 1 INSERT (chunk 分割) で upsert する。

    各 dict は ``guild_id / channel_id / name / channel_type``。
    """
    values = list(channels)
    if not values:
        return 0
    now = datetime.now(UTC)
    for i in range(0, len(values), _BULK_UPSERT_CHUNK_SIZE):
        chunk = values[i : i + _BULK_UPSERT_CHUNK_SIZE]
        stmt = pg_insert(ChannelMeta).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_channel_meta",
            set_={
                "name": stmt.excluded.name,
                "channel_type": stmt.excluded.channel_type,
                "updated_at": now,
            },
        )
        await session.execute(stmt)
    await session.commit()
    return len(values)


async def is_user_bot(session: AsyncSession, user_id: str) -> bool:
    """``user_id`` が bot として記録されているかを返す。

    ``user_meta`` キャッシュに無い場合は ``False`` を返す (人扱い)。
    リアクションイベントで「メッセージ作者が bot か」を素早く判定するために使う。
    """
    stmt = select(UserMeta.is_bot).where(UserMeta.user_id == user_id)
    result = await session.execute(stmt)
    return bool(result.scalar_one_or_none())


async def get_user_meta_map(
    session: AsyncSession, user_ids: Iterable[str]
) -> dict[str, UserMeta]:
    ids = list(set(user_ids))
    if not ids:
        return {}
    stmt = select(UserMeta).where(UserMeta.user_id.in_(ids))
    result = await session.execute(stmt)
    return {meta.user_id: meta for meta in result.scalars().all()}


async def get_channel_meta_map(
    session: AsyncSession, guild_id: str, channel_ids: Iterable[str]
) -> dict[str, ChannelMeta]:
    ids = list(set(channel_ids))
    if not ids:
        return {}
    stmt = select(ChannelMeta).where(
        and_(
            ChannelMeta.guild_id == guild_id,
            ChannelMeta.channel_id.in_(ids),
        )
    )
    result = await session.execute(stmt)
    return {meta.channel_id: meta for meta in result.scalars().all()}
