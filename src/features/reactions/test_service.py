"""Postgres-backed tests for the reactions service.

カバー:
    - 初の絵文字で record_reaction_add が True (= daily_stats を加算する)
    - 同一 (message, reactor) で 2 つ目の絵文字は False (= 加算しない)
    - 重複イベント (同じ emoji) は False (= 加算しない、no-op)
    - 最後の絵文字を外したら record_reaction_remove が True
    - 他絵文字が残っているうちは False
    - 元から無い emoji の remove は False
    - UNIQUE 制約 smoke
"""

import pytest
import sqlalchemy.exc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Reaction
from src.features.reactions.service import (
    record_reaction_add,
    record_reaction_remove,
)


async def _add(
    db_session: AsyncSession,
    *,
    message_id: str = "1001",
    reactor_id: str = "2001",
    author_id: str = "3001",
    emoji: str = "👍",
) -> bool:
    return await record_reaction_add(
        db_session,
        guild_id="9001",
        channel_id="5001",
        message_id=message_id,
        reactor_id=reactor_id,
        message_author_id=author_id,
        emoji=emoji,
    )


# =============================================================================
# record_reaction_add
# =============================================================================


async def test_first_emoji_returns_true(db_session: AsyncSession) -> None:
    """初の絵文字なら daily_stats 加算指示 (True) が返る。"""
    assert await _add(db_session) is True


async def test_second_emoji_same_reactor_returns_false(
    db_session: AsyncSession,
) -> None:
    """同 reactor が別絵文字を付け足しても 2 回目は False。"""
    await _add(db_session, emoji="👍")
    assert await _add(db_session, emoji="❤️") is False


async def test_duplicate_event_returns_false(db_session: AsyncSession) -> None:
    """同じ emoji の重複イベント (Discord の二重配信等) は False (no-op)。"""
    await _add(db_session, emoji="👍")
    assert await _add(db_session, emoji="👍") is False


async def test_different_reactors_each_get_true(db_session: AsyncSession) -> None:
    """別 reactor は別カウント。それぞれ True を返す。"""
    assert await _add(db_session, reactor_id="2001") is True
    assert await _add(db_session, reactor_id="2002") is True


async def test_different_messages_each_get_true(db_session: AsyncSession) -> None:
    """同 reactor でも別メッセージなら別カウントで True。"""
    assert await _add(db_session, message_id="1001") is True
    assert await _add(db_session, message_id="1002") is True


# =============================================================================
# record_reaction_remove
# =============================================================================


async def test_last_emoji_removal_returns_true(db_session: AsyncSession) -> None:
    """唯一の絵文字を外したら daily_stats 減算指示 (True)。"""
    await _add(db_session, emoji="👍")
    result = await record_reaction_remove(
        db_session, message_id="1001", reactor_id="2001", emoji="👍"
    )
    assert result is True


async def test_non_last_emoji_removal_returns_false(
    db_session: AsyncSession,
) -> None:
    """他絵文字が残っていれば False (まだリアクター扱い)。"""
    await _add(db_session, emoji="👍")
    await _add(db_session, emoji="❤️")
    result = await record_reaction_remove(
        db_session, message_id="1001", reactor_id="2001", emoji="👍"
    )
    assert result is False


async def test_remove_nonexistent_emoji_returns_false(
    db_session: AsyncSession,
) -> None:
    """記録に無い emoji を remove しても no-op で False (追跡開始前等)。"""
    result = await record_reaction_remove(
        db_session, message_id="1001", reactor_id="2001", emoji="👍"
    )
    assert result is False


async def test_add_after_remove_is_first_again(db_session: AsyncSession) -> None:
    """全部外した後に再度 react すると初の絵文字扱いで True。"""
    await _add(db_session, emoji="👍")
    await record_reaction_remove(
        db_session, message_id="1001", reactor_id="2001", emoji="👍"
    )
    assert await _add(db_session, emoji="🔥") is True


# =============================================================================
# Schema smoke (UNIQUE)
# =============================================================================


async def test_reaction_unique_constraint(db_session: AsyncSession) -> None:
    """同一 (message, reactor, emoji) の直接 INSERT は IntegrityError。"""
    db_session.add(
        Reaction(
            guild_id="9001",
            channel_id="5001",
            message_id="1001",
            reactor_id="2001",
            message_author_id="3001",
            emoji="👍",
        )
    )
    await db_session.commit()

    db_session.add(
        Reaction(
            guild_id="9001",
            channel_id="5001",
            message_id="1001",
            reactor_id="2001",
            message_author_id="3001",
            emoji="👍",
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await db_session.commit()


async def test_reaction_rows_persisted_for_audit(db_session: AsyncSession) -> None:
    """``record_reaction_add`` が実行後に Reaction 行がちゃんと残る (監査用)。"""
    await _add(db_session, emoji="👍")
    await _add(db_session, emoji="❤️")
    rows = (await db_session.execute(select(Reaction))).scalars().all()
    assert len(rows) == 2
    assert {r.emoji for r in rows} == {"👍", "❤️"}
