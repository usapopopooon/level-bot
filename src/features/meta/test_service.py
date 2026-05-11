"""Postgres-backed tests for meta service (user / channel display lookup)."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.meta.service import (
    bulk_upsert_channel_meta,
    bulk_upsert_user_meta,
    get_channel_meta_map,
    get_user_meta_map,
    is_user_bot,
    upsert_channel_meta,
    upsert_user_meta,
)

# =============================================================================
# upsert_user_meta / upsert_channel_meta
# =============================================================================


async def test_upsert_user_meta_inserts_then_updates(
    db_session: AsyncSession,
) -> None:
    await upsert_user_meta(
        db_session,
        user_id="100",
        display_name="Alice",
        avatar_url="https://cdn/a.png",
        is_bot=False,
    )
    await upsert_user_meta(
        db_session,
        user_id="100",
        display_name="Alice2",
        avatar_url="https://cdn/a2.png",
        is_bot=False,
    )

    metas = await get_user_meta_map(db_session, ["100"])
    assert metas["100"].display_name == "Alice2"
    assert metas["100"].avatar_url == "https://cdn/a2.png"


async def test_upsert_channel_meta_inserts_then_updates(
    db_session: AsyncSession,
) -> None:
    await upsert_channel_meta(
        db_session,
        guild_id="1",
        channel_id="2",
        name="general",
        channel_type="TextChannel",
    )
    await upsert_channel_meta(
        db_session,
        guild_id="1",
        channel_id="2",
        name="general-renamed",
        channel_type="TextChannel",
    )

    metas = await get_channel_meta_map(db_session, "1", ["2"])
    assert metas["2"].name == "general-renamed"


async def test_channel_meta_scoped_per_guild(db_session: AsyncSession) -> None:
    """同一 channel_id でも guild_id が違えば別レコードになる。"""
    await upsert_channel_meta(
        db_session, guild_id="1", channel_id="2", name="A", channel_type="Text"
    )
    await upsert_channel_meta(
        db_session, guild_id="3", channel_id="2", name="B", channel_type="Text"
    )

    g1 = await get_channel_meta_map(db_session, "1", ["2"])
    g2 = await get_channel_meta_map(db_session, "3", ["2"])
    assert g1["2"].name == "A"
    assert g2["2"].name == "B"


# =============================================================================
# bulk_upsert_user_meta / bulk_upsert_channel_meta
# =============================================================================


async def test_bulk_upsert_user_meta_inserts_then_updates(
    db_session: AsyncSession,
) -> None:
    """新規 + 既存更新が混在しても 1 命令で正しく処理される (起動時 backfill 用)。"""
    count1 = await bulk_upsert_user_meta(
        db_session,
        [
            {
                "user_id": "100",
                "display_name": "Alice",
                "avatar_url": None,
                "is_bot": False,
            },
            {
                "user_id": "200",
                "display_name": "Bob",
                "avatar_url": None,
                "is_bot": False,
            },
        ],
    )
    assert count1 == 2

    count2 = await bulk_upsert_user_meta(
        db_session,
        [
            # 既存を更新
            {
                "user_id": "100",
                "display_name": "Alice2",
                "avatar_url": None,
                "is_bot": False,
            },
            # 新規
            {
                "user_id": "300",
                "display_name": "Charlie",
                "avatar_url": None,
                "is_bot": False,
            },
        ],
    )
    assert count2 == 2

    metas = await get_user_meta_map(db_session, ["100", "200", "300"])
    assert metas["100"].display_name == "Alice2"
    assert metas["200"].display_name == "Bob"
    assert metas["300"].display_name == "Charlie"


async def test_bulk_upsert_user_meta_empty_returns_zero(
    db_session: AsyncSession,
) -> None:
    """空 iterable は no-op (0 件返る、SQL 投げない)。"""
    assert await bulk_upsert_user_meta(db_session, []) == 0


async def test_bulk_upsert_user_meta_handles_chunk_boundary(
    db_session: AsyncSession,
) -> None:
    """500 行を超えるデータでも chunk 分割で全件処理される。"""
    user_ids = [str(1_000_000 + i) for i in range(601)]
    payload = [
        {
            "user_id": uid,
            "display_name": f"user{uid}",
            "avatar_url": None,
            "is_bot": False,
        }
        for uid in user_ids
    ]
    count = await bulk_upsert_user_meta(db_session, payload)
    assert count == 601
    metas = await get_user_meta_map(db_session, user_ids)
    assert len(metas) == 601


async def test_bulk_upsert_channel_meta_inserts_then_updates(
    db_session: AsyncSession,
) -> None:
    await bulk_upsert_channel_meta(
        db_session,
        [
            {
                "guild_id": "1001",
                "channel_id": "100",
                "name": "general",
                "channel_type": "TextChannel",
            },
            {
                "guild_id": "1001",
                "channel_id": "200",
                "name": "voice-1",
                "channel_type": "VoiceChannel",
            },
        ],
    )
    await bulk_upsert_channel_meta(
        db_session,
        [
            {
                "guild_id": "1001",
                "channel_id": "100",
                "name": "general-renamed",
                "channel_type": "TextChannel",
            },
        ],
    )

    metas = await get_channel_meta_map(db_session, "1001", ["100", "200"])
    assert metas["100"].name == "general-renamed"
    assert metas["200"].name == "voice-1"


async def test_bulk_upsert_channel_meta_empty_returns_zero(
    db_session: AsyncSession,
) -> None:
    assert await bulk_upsert_channel_meta(db_session, []) == 0


# =============================================================================
# Empty-input early-return guards
# =============================================================================


async def test_get_user_meta_map_empty_input_returns_empty(
    db_session: AsyncSession,
) -> None:
    """空 iterable で呼ばれた場合 SQL を投げずに即返す (パフォーマンス保証)。"""
    result = await get_user_meta_map(db_session, [])
    assert result == {}


async def test_get_channel_meta_map_empty_input_returns_empty(
    db_session: AsyncSession,
) -> None:
    result = await get_channel_meta_map(db_session, "1", [])
    assert result == {}


# =============================================================================
# is_user_bot
# =============================================================================


async def test_is_user_bot_returns_true_for_bot(db_session: AsyncSession) -> None:
    await upsert_user_meta(
        db_session,
        user_id="100",
        display_name="bot",
        avatar_url=None,
        is_bot=True,
    )
    assert await is_user_bot(db_session, "100") is True


async def test_is_user_bot_returns_false_for_human(db_session: AsyncSession) -> None:
    await upsert_user_meta(
        db_session,
        user_id="100",
        display_name="alice",
        avatar_url=None,
        is_bot=False,
    )
    assert await is_user_bot(db_session, "100") is False


async def test_is_user_bot_returns_false_for_unknown_user(
    db_session: AsyncSession,
) -> None:
    """user_meta に記録のないユーザーは「人」として扱う (False を返す)。"""
    assert await is_user_bot(db_session, "999") is False
