"""Postgres-backed tests for upsert helpers (``ON CONFLICT DO UPDATE``).

これらは sqlite では動かない (PG 専用方言) ため、PG コンテナ前提で動かす。

カバー:
    - ``upsert_guild`` (新規挿入 / 更新 / settings 自動作成)
    - ``increment_message_stat`` (初回挿入 / 再呼び出しで加算)
    - ``add_voice_seconds`` (累積 / 上限クランプ / ゼロ早期 return)
    - ``upsert_user_meta`` / ``upsert_channel_meta`` (新規 / 更新)
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_VOICE_SESSION_SECONDS
from src.database.models import DailyStat, Guild, GuildSettings, VoiceSession
from src.services.stats_service import (
    add_excluded_channel,
    add_voice_seconds,
    bulk_upsert_channel_meta,
    bulk_upsert_user_meta,
    flush_active_voice_sessions_to_daily_stats,
    get_channel_meta_map,
    get_user_meta_map,
    increment_message_stat,
    list_active_voice_sessions,
    upsert_channel_meta,
    upsert_guild,
    upsert_user_meta,
)

# =============================================================================
# upsert_guild
# =============================================================================


async def test_upsert_guild_creates_with_default_settings(
    db_session: AsyncSession,
) -> None:
    guild = await upsert_guild(
        db_session,
        guild_id="100",
        name="Test Guild",
        icon_url="https://cdn/icon.png",
        member_count=42,
    )
    assert guild.guild_id == "100"
    assert guild.is_active is True

    # 自動生成された default settings が紐づくこと
    settings_row = (
        await db_session.execute(
            select(GuildSettings).where(GuildSettings.guild_pk == guild.id)
        )
    ).scalar_one()
    assert settings_row.tracking_enabled is True
    assert settings_row.count_bots is False
    assert settings_row.public is True


async def test_upsert_guild_updates_existing_without_duplicating_settings(
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id="200",
        name="Old Name",
        icon_url=None,
        member_count=1,
    )
    await upsert_guild(
        db_session,
        guild_id="200",
        name="New Name",
        icon_url="https://cdn/new.png",
        member_count=99,
    )

    rows = (await db_session.execute(select(Guild))).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "New Name"
    assert rows[0].icon_url == "https://cdn/new.png"
    assert rows[0].member_count == 99

    # settings は重複生成されない
    settings_count = (await db_session.execute(select(GuildSettings))).scalars().all()
    assert len(settings_count) == 1


async def test_upsert_guild_reactivates_inactive_guild(
    db_session: AsyncSession,
) -> None:
    guild = await upsert_guild(
        db_session, guild_id="300", name="g", icon_url=None, member_count=0
    )
    guild.is_active = False
    await db_session.commit()

    await upsert_guild(
        db_session, guild_id="300", name="g", icon_url=None, member_count=0
    )
    refreshed = (
        await db_session.execute(select(Guild).where(Guild.guild_id == "300"))
    ).scalar_one()
    assert refreshed.is_active is True


# =============================================================================
# increment_message_stat
# =============================================================================


async def test_increment_message_stat_creates_first_row(
    db_session: AsyncSession,
) -> None:
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=42,
        attachment_count=1,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.message_count == 1
    assert row.char_count == 42
    assert row.attachment_count == 1


async def test_increment_message_stat_accumulates(db_session: AsyncSession) -> None:
    for char_count in (10, 20, 30):
        await increment_message_stat(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
            char_count=char_count,
            attachment_count=0,
        )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 1
    assert rows[0].message_count == 3
    assert rows[0].char_count == 60


async def test_increment_message_stat_separates_dates(
    db_session: AsyncSession,
) -> None:
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=10,
        attachment_count=0,
    )
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 2),
        char_count=20,
        attachment_count=0,
    )
    rows = (
        (await db_session.execute(select(DailyStat).order_by(DailyStat.stat_date)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert [r.message_count for r in rows] == [1, 1]


async def test_increment_message_stat_separates_channels(
    db_session: AsyncSession,
) -> None:
    """チャンネルが違えば別行になる (channel-level 集計の前提)。"""
    for ch in ("A", "B"):
        await increment_message_stat(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id=ch,
            stat_date=date(2026, 5, 1),
            char_count=5,
            attachment_count=0,
        )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 2


# =============================================================================
# add_voice_seconds
# =============================================================================


async def test_add_voice_seconds_inserts_first_row(db_session: AsyncSession) -> None:
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=600,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.voice_seconds == 600
    assert row.message_count == 0


async def test_add_voice_seconds_accumulates(db_session: AsyncSession) -> None:
    for s in (60, 120, 180):
        await add_voice_seconds(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
            seconds=s,
        )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.voice_seconds == 360


async def test_add_voice_seconds_clamps_at_max(db_session: AsyncSession) -> None:
    """単発呼び出しで MAX を超える値を渡しても上限に切り詰められる。"""
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=MAX_VOICE_SESSION_SECONDS * 10,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.voice_seconds == MAX_VOICE_SESSION_SECONDS


async def test_add_voice_seconds_skips_zero_or_negative(
    db_session: AsyncSession,
) -> None:
    """0 や負値は no-op (DB に書き込まない)。"""
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=0,
    )
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=-100,
    )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_add_voice_seconds_coexists_with_message_count(
    db_session: AsyncSession,
) -> None:
    """同一行にメッセージカウントが既にあっても、ボイス秒だけ加算される。"""
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=10,
        attachment_count=0,
    )
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=300,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.message_count == 1
    assert row.char_count == 10
    assert row.voice_seconds == 300


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
        db_session, guild_id="g1", channel_id="c", name="A", channel_type="Text"
    )
    await upsert_channel_meta(
        db_session, guild_id="g2", channel_id="c", name="B", channel_type="Text"
    )

    g1 = await get_channel_meta_map(db_session, "g1", ["c"])
    g2 = await get_channel_meta_map(db_session, "g2", ["c"])
    assert g1["c"].name == "A"
    assert g2["c"].name == "B"


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
# flush_active_voice_sessions_to_daily_stats (Bot 再起動時のフラッシュ)
# =============================================================================


async def test_flush_writes_elapsed_to_daily_stats(
    db_session: AsyncSession,
) -> None:
    """進行中セッションが daily_stats に保存され、再起動を挟んでも時間が消えない。"""
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )
    await db_session.commit()

    flushed = await flush_active_voice_sessions_to_daily_stats(db_session)
    assert flushed == 1

    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 1
    # ~30 分 = 1800 秒。多少のずれを許容
    assert 1700 <= rows[0].voice_seconds <= 1900


async def test_flush_returns_zero_when_no_active_sessions(
    db_session: AsyncSession,
) -> None:
    assert await flush_active_voice_sessions_to_daily_stats(db_session) == 0


async def test_flush_skips_zombie_session_over_24h(
    db_session: AsyncSession,
) -> None:
    """24h を超える zombie session は不正値防止のためスキップされる。"""
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(hours=48),
        )
    )
    await db_session.commit()

    flushed = await flush_active_voice_sessions_to_daily_stats(db_session)
    assert flushed == 0
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_flush_skips_excluded_channel(db_session: AsyncSession) -> None:
    """除外チャンネルのセッションは flush で daily_stats に書かれない。"""
    await add_excluded_channel(db_session, "1001", "3001")
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    flushed = await flush_active_voice_sessions_to_daily_stats(db_session)
    assert flushed == 0
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_flush_does_not_remove_sessions(db_session: AsyncSession) -> None:
    """flush 自体は session を残す (purge は別関数の責務)。"""
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    await flush_active_voice_sessions_to_daily_stats(db_session)
    sessions = await list_active_voice_sessions(db_session)
    assert len(sessions) == 1
