from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import discord
import pytest

from src.cogs import tracking as tracking_mod
from src.cogs.tracking import TrackingCog
from src.database.models import LevelRoleAward


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class _Guild:
    def __init__(self, roles: list[_Role]) -> None:
        self.id = 1001
        self._roles = {r.id: r for r in roles}
        self._channels: dict[int, object] = {}
        self._members: dict[int, object] = {}

    def get_role(self, role_id: int) -> _Role | None:
        return self._roles.get(role_id)

    def get_channel_or_thread(self, channel_id: int) -> object | None:
        return self._channels.get(channel_id)

    def get_member(self, user_id: int) -> object | None:
        return self._members.get(user_id)


@pytest.mark.asyncio
async def test_grant_level_roles_keeps_highest_per_slot_and_removes_lower() -> None:
    role11 = _Role(11)
    role12 = _Role(12)
    role21 = _Role(21)
    role99 = _Role(99)
    guild = _Guild([role11, role12, role21, role99])

    member = SimpleNamespace(
        guild=guild,
        id=2001,
        roles=[role11, role99],
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    rules = [
        LevelRoleAward(guild_id="1001", slot=1, level=3, role_id="11"),
        LevelRoleAward(guild_id="1001", slot=1, level=10, role_id="12"),
        LevelRoleAward(guild_id="1001", slot=2, level=5, role_id="21"),
    ]

    changed = await cog._grant_level_roles_from_rules(
        member=member,  # type: ignore[arg-type]
        level=10,
        rules=rules,
    )

    assert changed is True
    member.add_roles.assert_awaited_once()
    added_ids = {r.id for r in member.add_roles.await_args.args}
    assert added_ids == {12, 21}

    member.remove_roles.assert_awaited_once()
    removed_ids = {r.id for r in member.remove_roles.await_args.args}
    assert removed_ids == {11}


@pytest.mark.asyncio
async def test_grant_level_roles_noop_when_member_already_matches_selection() -> None:
    role12 = _Role(12)
    role21 = _Role(21)
    guild = _Guild([role12, role21])

    member = SimpleNamespace(
        guild=guild,
        id=2001,
        roles=[role12, role21],
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    rules = [
        LevelRoleAward(guild_id="1001", slot=1, level=10, role_id="12"),
        LevelRoleAward(guild_id="1001", slot=2, level=5, role_id="21"),
    ]

    changed = await cog._grant_level_roles_from_rules(
        member=member,  # type: ignore[arg-type]
        level=10,
        rules=rules,
    )

    assert changed is False
    member.add_roles.assert_not_awaited()
    member.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_level_roles_treats_missing_stats_as_level_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role11 = _Role(11)
    guild = _Guild([role11])
    member = SimpleNamespace(guild=guild, id=2001, roles=[])

    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.list_level_role_awards_for_grant",
        AsyncMock(
            return_value=[
                LevelRoleAward(guild_id="1001", slot=1, level=0, role_id="11")
            ]
        ),
    )
    monkeypatch.setattr(
        tracking_mod,
        "get_user_lifetime_levels",
        AsyncMock(return_value=None),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    grant_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(cog, "_grant_level_roles_from_rules", grant_mock)

    await cog._apply_level_roles_if_needed(member=member, force=True)  # type: ignore[arg-type]

    grant_mock.assert_awaited_once()
    assert grant_mock.await_args is not None
    assert grant_mock.await_args.kwargs["level"] == 0


@pytest.mark.asyncio
async def test_notify_level_up_sends_without_mention() -> None:
    role11 = _Role(11)
    guild = _Guild([role11])
    member = SimpleNamespace(
        guild=guild, id=2001, mention="<@2001>", display_name="Level User"
    )
    place = SimpleNamespace(send=AsyncMock())

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    await cog._notify_level_up(member=member, new_level=7, place=place)  # type: ignore[arg-type]

    place.send.assert_awaited_once()
    assert place.send.await_args is not None
    assert "content" not in place.send.await_args.kwargs
    embed = place.send.await_args.kwargs["embed"]
    assert (
        embed.description
        == "レベルアップ！ **Level User** さんが **Lv 7** になりました。"
    )


@pytest.mark.asyncio
async def test_get_total_level_can_exclude_live_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    levels = SimpleNamespace(total=SimpleNamespace(level=4))
    get_levels_mock = AsyncMock(return_value=levels)

    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(tracking_mod, "get_user_lifetime_levels", get_levels_mock)

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    level = await cog._get_total_level("1001", "2001", include_live_voice=False)

    assert level == 4
    get_levels_mock.assert_awaited_once()
    assert get_levels_mock.await_args is not None
    assert get_levels_mock.await_args.kwargs["include_live_voice"] is False


@pytest.mark.asyncio
async def test_voice_move_levelup_uses_destination_channel_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guild = _Guild([])
    from_channel = SimpleNamespace(id=10, name="from-vc")
    to_channel = SimpleNamespace(id=20, name="to-vc")
    notify_place = SimpleNamespace(send=AsyncMock())
    guild._channels[to_channel.id] = notify_place

    member = SimpleNamespace(
        guild=guild,
        id=2001,
        bot=False,
        display_name="alice",
        display_avatar=SimpleNamespace(url="https://example.invalid/a.png"),
    )
    before = SimpleNamespace(channel=from_channel)
    after = SimpleNamespace(
        channel=to_channel,
        self_mute=False,
        self_deaf=False,
    )

    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.end_voice_session",
        AsyncMock(
            return_value=SimpleNamespace(
                joined_at=datetime.now(UTC) - timedelta(minutes=5),
                channel_id=str(from_channel.id),
            )
        ),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.is_channel_excluded",
        AsyncMock(return_value=False),
    )
    get_levels_mock = AsyncMock(
        return_value=SimpleNamespace(total=SimpleNamespace(level=1))
    )
    monkeypatch.setattr(tracking_mod, "get_user_lifetime_levels", get_levels_mock)
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.add_voice_seconds",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.start_voice_session",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.meta_service.upsert_user_meta",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.meta_service.upsert_channel_meta",
        AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    progress_mock = AsyncMock()
    monkeypatch.setattr(cog, "_process_level_progress", progress_mock)

    await cog.on_voice_state_update(
        member=cast(discord.Member, member),
        before=cast(discord.VoiceState, before),
        after=cast(discord.VoiceState, after),
    )

    get_levels_mock.assert_awaited_once()
    assert get_levels_mock.await_args is not None
    assert get_levels_mock.await_args.kwargs["include_live_voice"] is False

    progress_mock.assert_awaited_once()
    assert progress_mock.await_args is not None
    assert progress_mock.await_args.kwargs["place"] is notify_place


@pytest.mark.asyncio
async def test_live_voice_level_loop_notifies_when_live_voice_crosses_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guild = _Guild([])
    voice_channel = SimpleNamespace(id=10, name="voice")
    notify_place = SimpleNamespace(send=AsyncMock())
    guild._channels[voice_channel.id] = notify_place
    member = SimpleNamespace(
        guild=guild,
        id=2001,
        bot=False,
        voice=SimpleNamespace(channel=voice_channel),
    )
    guild._members[member.id] = member

    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.list_active_voice_sessions",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    guild_id=str(guild.id),
                    user_id=str(member.id),
                    channel_id=str(voice_channel.id),
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.get_guild_settings",
        AsyncMock(
            return_value=SimpleNamespace(tracking_enabled=True, count_bots=False)
        ),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.is_channel_excluded",
        AsyncMock(return_value=False),
    )
    get_levels_mock = AsyncMock(
        return_value=(
            SimpleNamespace(total=SimpleNamespace(level=1)),
            SimpleNamespace(total=SimpleNamespace(level=2)),
        )
    )
    monkeypatch.setattr(
        tracking_mod,
        "get_user_lifetime_levels_static_and_live",
        get_levels_mock,
    )

    bot = SimpleNamespace(
        get_guild=lambda guild_id: guild if guild_id == guild.id else None
    )
    cog = TrackingCog(bot)  # type: ignore[arg-type]
    progress_mock = AsyncMock()
    monkeypatch.setattr(cog, "_process_level_progress", progress_mock)

    await cog._live_voice_level_loop()

    progress_mock.assert_awaited_once()
    assert progress_mock.await_args is not None
    assert progress_mock.await_args.kwargs["member"] is member
    assert progress_mock.await_args.kwargs["prev_level"] == 1
    assert progress_mock.await_args.kwargs["new_level"] == 2
    assert progress_mock.await_args.kwargs["place"] is notify_place
    assert cog._live_voice_level_cache[(str(guild.id), str(member.id))] == 2
    get_levels_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_leave_uses_live_voice_notified_level_as_previous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guild = _Guild([])
    from_channel = SimpleNamespace(id=10, name="voice")
    member = SimpleNamespace(
        guild=guild,
        id=2001,
        bot=False,
        display_name="alice",
        display_avatar=SimpleNamespace(url="https://example.invalid/a.png"),
    )
    before = SimpleNamespace(channel=from_channel)
    after = SimpleNamespace(channel=None)

    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.end_voice_session",
        AsyncMock(
            return_value=SimpleNamespace(
                joined_at=datetime.now(UTC) - timedelta(minutes=5),
                channel_id=str(from_channel.id),
            )
        ),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.guilds_service.is_channel_excluded",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        tracking_mod,
        "get_user_lifetime_levels",
        AsyncMock(return_value=SimpleNamespace(total=SimpleNamespace(level=1))),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.add_voice_seconds",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.meta_service.upsert_user_meta",
        AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    cog._live_voice_level_cache[(str(guild.id), str(member.id))] = 2
    progress_mock = AsyncMock()
    monkeypatch.setattr(cog, "_process_level_progress", progress_mock)

    await cog.on_voice_state_update(
        member=cast(discord.Member, member),
        before=cast(discord.VoiceState, before),
        after=cast(discord.VoiceState, after),
    )

    progress_mock.assert_awaited_once()
    assert progress_mock.await_args is not None
    assert progress_mock.await_args.kwargs["prev_level"] == 2
    assert (str(guild.id), str(member.id)) not in cog._live_voice_level_cache
