"""Postgres-backed tests for guild + settings + excluded-channel service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ExcludedChannel, Guild, GuildSettings
from src.features.guilds.service import (
    add_excluded_channel,
    is_channel_excluded,
    list_active_guilds,
    list_excluded_channels,
    mark_guild_inactive,
    remove_excluded_channel,
    upsert_guild,
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
# list_active_guilds (修正 3 の回帰: lazy load の MissingGreenlet 防止)
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
# UNIQUE constraint smoke check (cross-cutting; lives here since this is the
# excluded_channels feature)
# =============================================================================


async def test_excluded_channel_unique_constraint(
    db_session: AsyncSession,
) -> None:
    """同一 (guild, channel) の重複は UNIQUE 制約で拒否される。"""
    import pytest
    import sqlalchemy.exc

    db_session.add(ExcludedChannel(guild_id="1", channel_id="2"))
    await db_session.commit()

    db_session.add(ExcludedChannel(guild_id="1", channel_id="2"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await db_session.commit()
