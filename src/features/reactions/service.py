"""Individual reaction event records + per-message dedup for leveling.

``reactions`` テーブルに 1 リアクションイベントごとに 1 行を持ち:
    - 監査用途 (「誰が誰に何を付けた / もらった」逆引き)
    - レベル算出の重複検出 (1 message × 1 reactor = 1 加算)

``record_reaction_add`` / ``record_reaction_remove`` は cog から呼ばれ、
それぞれ「daily_stats を加算/減算すべきか」を bool で返す。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Reaction


async def _count_reactor_emojis_on_message(
    session: AsyncSession, *, message_id: str, reactor_id: str
) -> int:
    """``reactor_id`` が ``message_id`` に付けている絵文字の数。"""
    stmt = select(func.count(Reaction.id)).where(
        and_(
            Reaction.message_id == message_id,
            Reaction.reactor_id == reactor_id,
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def record_reaction_add(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    message_id: str,
    reactor_id: str,
    message_author_id: str,
    emoji: str,
) -> bool:
    """リアクション 1 件を ``reactions`` 表に記録する。

    Returns:
        True なら **daily_stats を加算すべき** (このリアクターが本メッセージに
        付ける初の絵文字)。False なら既に他絵文字で計上済み or 重複イベント
        なので daily_stats は触らない。
    """
    stmt = (
        pg_insert(Reaction)
        .values(
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            reactor_id=reactor_id,
            message_author_id=message_author_id,
            emoji=emoji,
        )
        .on_conflict_do_nothing(constraint="uq_reaction")
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    if (result.rowcount or 0) == 0:
        return False  # 重複イベント (同じ emoji が既に存在)
    total = await _count_reactor_emojis_on_message(
        session, message_id=message_id, reactor_id=reactor_id
    )
    return total == 1  # 今 insert したのが唯一 = 初の絵文字


async def record_reaction_remove(
    session: AsyncSession,
    *,
    message_id: str,
    reactor_id: str,
    emoji: str,
) -> bool:
    """リアクション 1 件を ``reactions`` 表から削除する。

    Returns:
        True なら **daily_stats を減算すべき** (このリアクターの最後の絵文字を
        外した)。False なら他絵文字が残っているか、そもそも記録が無い。
    """
    stmt = delete(Reaction).where(
        and_(
            Reaction.message_id == message_id,
            Reaction.reactor_id == reactor_id,
            Reaction.emoji == emoji,
        )
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    if (result.rowcount or 0) == 0:
        return False  # そもそもこの emoji の記録が無い (追跡開始前など)
    remaining = await _count_reactor_emojis_on_message(
        session, message_id=message_id, reactor_id=reactor_id
    )
    return remaining == 0  # 全絵文字外し終わった


async def delete_message_reactions(session: AsyncSession, *, message_id: str) -> int:
    """``message_id`` の全リアクション行を削除する。

    ``on_raw_reaction_clear`` (モデレーターが一括クリア) 時に呼ぶ。
    daily_stats には触らない (実際に行われた engagement は履歴に残す方針)。

    Returns:
        削除件数。
    """
    stmt = delete(Reaction).where(Reaction.message_id == message_id)
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return result.rowcount or 0


async def delete_emoji_reactions(
    session: AsyncSession, *, message_id: str, emoji: str
) -> int:
    """``message_id`` × ``emoji`` の全リアクション行を削除する。

    ``on_raw_reaction_clear_emoji`` で呼ぶ。同上で daily_stats は触らない。
    """
    stmt = delete(Reaction).where(
        and_(Reaction.message_id == message_id, Reaction.emoji == emoji)
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return result.rowcount or 0


async def purge_old_reactions(
    session: AsyncSession, *, older_than_days: int = 180
) -> int:
    """``older_than_days`` 日より古い個別 ``reactions`` 行を削除する。

    daily_stats の値は保持される (集計済みなので)。長期データ量を抑えるための
    cron 等から呼ぶことを想定。現状自動実行はしない。

    Returns:
        削除件数。
    """
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    stmt = delete(Reaction).where(Reaction.created_at < cutoff)
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return result.rowcount or 0
