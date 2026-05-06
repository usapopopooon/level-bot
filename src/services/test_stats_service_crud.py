"""DB-backed CRUD / lifecycle tests for stats_service.

カバー:
    - ``purge_all_voice_sessions``: 修正 2 で追加したヘルパー
    - ``list_active_guilds``: 修正 3 (``selectinload(Guild.settings)`` 回帰)
    - ``mark_guild_inactive``: ギルド退場フラグ
    - excluded_channels CRUD
    - voice session lifecycle (start/end の置換動作)
    - meta_map の空 iterable 早期 return
    - UNIQUE 制約 (daily_stat / excluded_channel)

upsert (``ON CONFLICT``) と集計クエリは別ファイルでカバー:
    - ``test_stats_service_upserts.py``
    - ``test_stats_service_aggregations.py``
"""

from datetime import date

import pytest
import sqlalchemy.exc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    DailyStat,
    ExcludedChannel,
    Guild,
    GuildSettings,
    VoiceSession,
)
from src.services.stats_service import (
    add_excluded_channel,
    end_voice_session,
    get_channel_meta_map,
    get_user_meta_map,
    is_channel_excluded,
    list_active_guilds,
    list_active_voice_sessions,
    list_excluded_channels,
    mark_guild_inactive,
    purge_all_voice_sessions,
    remove_excluded_channel,
    start_voice_session,
)

# =============================================================================
# purge_all_voice_sessions  (修正 2 の回帰テスト)
# =============================================================================


async def test_purge_all_voice_sessions_removes_everything(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            VoiceSession(guild_id="1", user_id="2", channel_id="3"),
            VoiceSession(guild_id="1", user_id="4", channel_id="5"),
            VoiceSession(guild_id="9", user_id="10", channel_id="11"),
        ]
    )
    await db_session.commit()

    deleted = await purge_all_voice_sessions(db_session)
    assert deleted == 3
    assert await list_active_voice_sessions(db_session) == []


async def test_purge_all_voice_sessions_returns_zero_when_empty(
    db_session: AsyncSession,
) -> None:
    deleted = await purge_all_voice_sessions(db_session)
    assert deleted == 0


# =============================================================================
# list_active_guilds  (修正 3 の回帰テスト: lazy load の MissingGreenlet 防止)
# =============================================================================


async def test_list_active_guilds_eager_loads_settings(
    db_session: AsyncSession,
) -> None:
    guild = Guild(guild_id="1", name="1001")
    db_session.add(guild)
    await db_session.flush()
    db_session.add(GuildSettings(guild_pk=guild.id, public=True))
    await db_session.commit()

    guilds = await list_active_guilds(db_session)
    assert len(guilds) == 1
    # lazy load なら MissingGreenlet が出る属性アクセス
    assert guilds[0].settings is not None
    assert guilds[0].settings.public is True


async def test_list_active_guilds_filters_inactive(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Guild(guild_id="1", name="active", is_active=True),
            Guild(guild_id="2", name="inactive", is_active=False),
        ]
    )
    await db_session.commit()

    guilds = await list_active_guilds(db_session)
    names = [g.name for g in guilds]
    assert names == ["active"]


async def test_list_active_guilds_orders_by_name(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Guild(guild_id="1", name="zoo"),
            Guild(guild_id="2", name="alpha"),
            Guild(guild_id="3", name="midway"),
        ]
    )
    await db_session.commit()

    guilds = await list_active_guilds(db_session)
    assert [g.name for g in guilds] == ["alpha", "midway", "zoo"]


async def test_list_active_guilds_handles_no_settings(
    db_session: AsyncSession,
) -> None:
    """settings レコードが無いギルドでも relationship は None が返り例外は出ない。"""
    db_session.add(Guild(guild_id="1", name="no-settings"))
    await db_session.commit()

    guilds = await list_active_guilds(db_session)
    assert len(guilds) == 1
    assert guilds[0].settings is None


async def test_mark_guild_inactive_excludes_from_listing(
    db_session: AsyncSession,
) -> None:
    db_session.add(Guild(guild_id="1", name="g"))
    await db_session.commit()

    await mark_guild_inactive(db_session, "1")
    guilds = await list_active_guilds(db_session)
    assert guilds == []


async def test_mark_guild_inactive_is_noop_when_missing(
    db_session: AsyncSession,
) -> None:
    """存在しない guild_id でも例外を出さない。"""
    await mark_guild_inactive(db_session, "999")  # ← raise しないことの確認


# =============================================================================
# Excluded channels
# =============================================================================


async def test_add_excluded_channel_persists(db_session: AsyncSession) -> None:
    added = await add_excluded_channel(db_session, "1", "2")
    assert added is True
    assert await is_channel_excluded(db_session, "1", "2") is True


async def test_add_excluded_channel_is_idempotent(db_session: AsyncSession) -> None:
    await add_excluded_channel(db_session, "1", "2")
    again = await add_excluded_channel(db_session, "1", "2")
    assert again is False


async def test_remove_excluded_channel(db_session: AsyncSession) -> None:
    await add_excluded_channel(db_session, "1", "2")
    removed = await remove_excluded_channel(db_session, "1", "2")
    assert removed is True
    assert await is_channel_excluded(db_session, "1", "2") is False


async def test_remove_excluded_channel_returns_false_when_missing(
    db_session: AsyncSession,
) -> None:
    removed = await remove_excluded_channel(db_session, "1", "2")
    assert removed is False


async def test_list_excluded_channels_scoped_per_guild(
    db_session: AsyncSession,
) -> None:
    await add_excluded_channel(db_session, "1001", "3001")
    await add_excluded_channel(db_session, "1001", "3002")
    await add_excluded_channel(db_session, "1002", "3003")

    g1_channels = await list_excluded_channels(db_session, "1001")
    g2_channels = await list_excluded_channels(db_session, "1002")
    assert sorted(g1_channels) == ["3001", "3002"]
    assert g2_channels == ["3003"]


# =============================================================================
# Voice session lifecycle
# =============================================================================


async def test_start_voice_session_replaces_existing(db_session: AsyncSession) -> None:
    """同一ユーザーが新チャンネルへ移動した場合、旧セッションは置き換わる。"""
    await start_voice_session(db_session, guild_id="1", user_id="2", channel_id="100")
    await start_voice_session(db_session, guild_id="1", user_id="2", channel_id="200")

    sessions = await list_active_voice_sessions(db_session)
    assert len(sessions) == 1
    assert sessions[0].channel_id == "200"


async def test_end_voice_session_returns_record_then_deletes(
    db_session: AsyncSession,
) -> None:
    await start_voice_session(db_session, guild_id="1", user_id="2", channel_id="100")
    voice = await end_voice_session(db_session, guild_id="1", user_id="2")
    assert voice is not None
    assert voice.channel_id == "100"
    assert await list_active_voice_sessions(db_session) == []


async def test_end_voice_session_returns_none_when_no_session(
    db_session: AsyncSession,
) -> None:
    voice = await end_voice_session(db_session, guild_id="1", user_id="2")
    assert voice is None


# =============================================================================
# Meta caches
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
# Daily stats schema (composite UNIQUE constraint smoke check)
# =============================================================================


async def test_daily_stat_unique_constraint(db_session: AsyncSession) -> None:
    """同一 (guild, user, channel, date) の重複挿入は IntegrityError。

    upsert は本番 (Postgres) でしか使えないが、UNIQUE 制約自体は sqlite でも効く。
    """
    db_session.add(
        DailyStat(
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 1, 1),
            message_count=1,
        )
    )
    await db_session.commit()

    db_session.add(
        DailyStat(
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 1, 1),
            message_count=1,
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await db_session.commit()


async def test_excluded_channel_unique_constraint(
    db_session: AsyncSession,
) -> None:
    """同一 (guild, channel) の重複は UNIQUE 制約で拒否される。"""
    db_session.add(ExcludedChannel(guild_id="1", channel_id="2"))
    await db_session.commit()

    db_session.add(ExcludedChannel(guild_id="1", channel_id="2"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await db_session.commit()
