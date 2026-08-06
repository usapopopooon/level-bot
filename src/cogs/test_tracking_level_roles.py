from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest

from src.cogs import tracking as tracking_mod
from src.cogs.tracking import TrackingCog
from src.config import settings
from src.database.models import LevelRoleAward
from src.features.guilds import service as guilds_service
from src.features.voice_party import service as voice_party_service
from src.features.voice_party.service import VoicePartyResult
from src.features.voice_zen import service as voice_zen_service
from src.features.voice_zen.service import VoiceZenResult


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


@pytest.fixture(autouse=True)
def _mock_voice_zen_reconcile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        voice_zen_service,
        "get_active_voice_zen_user_id",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        voice_zen_service,
        "reconcile_voice_zen",
        AsyncMock(
            return_value=VoiceZenResult(
                "1001",
                "2001",
                "inactive",
                False,
                None,
                0,
                0,
                (),
                None,
                None,
                False,
            )
        ),
    )


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


def _component_label(component: object) -> str | None:
    return getattr(component, "label", None) or getattr(
        getattr(component, "item", None), "label", None
    )


def test_voice_zen_participants_exclude_bots_muted_and_afk() -> None:
    eligible = SimpleNamespace(id=11, bot=False, voice=SimpleNamespace())
    muted = SimpleNamespace(id=12, bot=False, voice=SimpleNamespace(self_mute=True))
    bot_member = SimpleNamespace(id=13, bot=True, voice=SimpleNamespace())
    guild = SimpleNamespace(afk_channel=None)
    channel = SimpleNamespace(id=2001, guild=guild, members=[eligible, bot_member])

    assert TrackingCog._voice_zen_participant_ids(channel) == ["11"]  # type: ignore[arg-type]

    channel.members = [eligible, muted, bot_member]
    assert TrackingCog._voice_zen_participant_ids(channel) == []  # type: ignore[arg-type]

    channel.members = [muted, bot_member]
    assert TrackingCog._voice_zen_participant_ids(channel) == []  # type: ignore[arg-type]

    channel.members = [eligible, bot_member]
    guild.afk_channel = channel
    assert TrackingCog._voice_zen_participant_ids(channel) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_startup_announces_unannounced_active_voice_party(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    guild = SimpleNamespace(id=1001)
    channel = SimpleNamespace(
        id=2001,
        guild=guild,
        members=[
            SimpleNamespace(id=11, bot=False),
            SimpleNamespace(id=12, bot=False),
            SimpleNamespace(id=13, bot=False),
        ],
        send=AsyncMock(return_value=SimpleNamespace(id=9999)),
        fetch_message=AsyncMock(),
    )
    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        guilds_service,
        "get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        guilds_service,
        "is_channel_excluded",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        voice_party_service,
        "reconcile_voice_party",
        AsyncMock(
            return_value=VoicePartyResult(
                "1001",
                "2001",
                "started",
                True,
                3,
                False,
                None,
                False,
                "tea_party",
                "inactive",
            )
        ),
    )
    mark_announced = AsyncMock(return_value=True)
    monkeypatch.setattr(
        voice_party_service,
        "mark_voice_party_announced",
        mark_announced,
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    await cog._reconcile_voice_party_channel(
        cast(discord.VoiceChannel | discord.StageChannel, channel),
        startup=True,
        accrue_elapsed=False,
    )

    assert channel.send.await_args.kwargs["embed"].title == (
        "☕ ティーパーティーボーナス開催中！"
    )
    mark_announced.assert_awaited_once_with(
        ANY,
        guild_id="1001",
        channel_id="2001",
        message_id="9999",
        tier="tea_party",
    )


@pytest.mark.asyncio
async def test_startup_does_not_repeat_existing_voice_party_announcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    channel = SimpleNamespace(
        id=2001,
        guild=SimpleNamespace(id=1001),
        members=[],
        send=AsyncMock(),
        fetch_message=AsyncMock(return_value=SimpleNamespace(id=9999)),
    )
    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        guilds_service,
        "get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        guilds_service,
        "is_channel_excluded",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        voice_party_service,
        "reconcile_voice_party",
        AsyncMock(
            return_value=VoicePartyResult(
                "1001",
                "2001",
                "continued",
                True,
                3,
                True,
                "9999",
                True,
                "tea_party",
                "tea_party",
            )
        ),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    await cog._reconcile_voice_party_channel(
        cast(discord.VoiceChannel | discord.StageChannel, channel),
        startup=True,
        accrue_elapsed=False,
    )

    channel.fetch_message.assert_awaited_once_with(9999)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_reannounces_when_saved_message_was_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    response = cast(Any, SimpleNamespace(status=404, reason="Not Found", headers={}))
    channel = SimpleNamespace(
        id=2001,
        guild=SimpleNamespace(id=1001),
        members=[],
        send=AsyncMock(return_value=SimpleNamespace(id=10000)),
        fetch_message=AsyncMock(side_effect=discord.NotFound(response, "missing")),
    )
    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        guilds_service,
        "get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        guilds_service,
        "is_channel_excluded",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        voice_party_service,
        "reconcile_voice_party",
        AsyncMock(
            return_value=VoicePartyResult(
                "1001",
                "2001",
                "continued",
                True,
                3,
                True,
                "9999",
                True,
                "tea_party",
                "tea_party",
            )
        ),
    )
    mark_unannounced = AsyncMock(return_value=True)
    mark_announced = AsyncMock(return_value=True)
    monkeypatch.setattr(
        voice_party_service,
        "mark_voice_party_unannounced",
        mark_unannounced,
    )
    monkeypatch.setattr(
        voice_party_service,
        "mark_voice_party_announced",
        mark_announced,
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    await cog._reconcile_voice_party_channel(
        cast(discord.VoiceChannel | discord.StageChannel, channel),
        startup=True,
        accrue_elapsed=False,
    )

    mark_unannounced.assert_awaited_once()
    assert channel.send.await_args.kwargs["embed"].title == (
        "☕ ティーパーティーボーナス開催中！"
    )
    mark_announced.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "startup", "expected_title"),
    [
        (
            VoicePartyResult(
                "1001",
                "2001",
                "upgraded",
                True,
                5,
                False,
                None,
                True,
                "tea_festival",
                "tea_party",
            ),
            False,
            "🫖 ティーフェスティバルボーナス開始！",
        ),
        (
            VoicePartyResult(
                "1001",
                "2001",
                "downgraded",
                True,
                4,
                False,
                None,
                True,
                "tea_party",
                "tea_festival",
            ),
            False,
            "☕ ティーパーティーボーナスに移行しました",
        ),
        (
            VoicePartyResult(
                "1001",
                "2001",
                "started",
                True,
                5,
                False,
                None,
                False,
                "tea_festival",
                "inactive",
            ),
            True,
            "🫖 ティーフェスティバルボーナス開催中！",
        ),
    ],
)
async def test_voice_party_tier_transition_uses_matching_embed(
    monkeypatch: pytest.MonkeyPatch,
    result: VoicePartyResult,
    startup: bool,
    expected_title: str,
) -> None:
    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    channel = SimpleNamespace(
        id=2001,
        guild=SimpleNamespace(id=1001),
        members=[],
        send=AsyncMock(return_value=SimpleNamespace(id=10001)),
        fetch_message=AsyncMock(),
    )
    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        guilds_service,
        "get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        guilds_service,
        "is_channel_excluded",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        voice_party_service,
        "reconcile_voice_party",
        AsyncMock(return_value=result),
    )
    mark_announced = AsyncMock(return_value=True)
    monkeypatch.setattr(
        voice_party_service,
        "mark_voice_party_announced",
        mark_announced,
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    await cog._reconcile_voice_party_channel(
        cast(discord.VoiceChannel | discord.StageChannel, channel),
        startup=startup,
        accrue_elapsed=not startup,
    )

    assert channel.send.await_args.kwargs["embed"].title == expected_title
    assert mark_announced.await_args is not None
    assert mark_announced.await_args.kwargs["tier"] == result.tier


@pytest.mark.asyncio
async def test_voice_zen_reward_and_end_are_announced_and_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield session

    member = SimpleNamespace(id=11)
    guild = SimpleNamespace(id=1001, get_member=lambda _user_id: member)
    channel = SimpleNamespace(
        id=2001,
        guild=guild,
        members=[
            SimpleNamespace(id=11, bot=False),
            SimpleNamespace(id=12, bot=False),
        ],
        send=AsyncMock(return_value=SimpleNamespace(id=10001)),
        fetch_message=AsyncMock(),
    )
    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        guilds_service,
        "get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        guilds_service,
        "is_channel_excluded",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        voice_party_service,
        "reconcile_voice_party",
        AsyncMock(
            return_value=VoicePartyResult(
                "1001",
                "2001",
                "inactive",
                False,
                2,
                False,
                None,
                False,
                "inactive",
                "inactive",
            )
        ),
    )
    monkeypatch.setattr(
        voice_zen_service,
        "reconcile_voice_zen",
        AsyncMock(
            return_value=VoiceZenResult(
                "1001",
                "2001",
                "ended",
                False,
                None,
                2,
                600,
                (voice_zen_service.VoiceZenAward("event-1", "11", 10, 10),),
                "11",
                "11",
                True,
                10,
            )
        ),
    )
    monkeypatch.setattr(
        voice_zen_service,
        "get_active_voice_zen_user_id",
        AsyncMock(return_value="11"),
    )
    monkeypatch.setattr(
        tracking_mod,
        "get_user_lifetime_levels",
        AsyncMock(
            side_effect=[
                SimpleNamespace(total=SimpleNamespace(level=1)),
                SimpleNamespace(total=SimpleNamespace(level=2)),
            ]
        ),
    )
    mark_announced = AsyncMock(return_value=True)
    monkeypatch.setattr(
        voice_zen_service,
        "mark_voice_zen_announced",
        mark_announced,
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    cog._process_level_progress = AsyncMock()  # type: ignore[method-assign]
    await cog._reconcile_voice_party_channel(
        cast(discord.VoiceChannel | discord.StageChannel, channel)
    )

    assert [call.kwargs["embed"].title for call in channel.send.await_args_list] == [
        "🧘 禅タイム開始！",
        "🍵 禅タイム終了",
    ]
    mark_announced.assert_awaited_once_with(
        session,
        guild_id="1001",
        channel_id="2001",
        event_id="event-1",
    )
    cog._process_level_progress.assert_awaited_once_with(
        member=member,
        prev_level=1,
        place=channel,
        new_level=2,
    )


@pytest.mark.asyncio
async def test_three_humans_are_sent_to_party_not_solo_zen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield object()

    members = [
        SimpleNamespace(id=user_id, bot=False, voice=SimpleNamespace())
        for user_id in (11, 12, 13)
    ]
    channel = SimpleNamespace(
        id=2001,
        guild=SimpleNamespace(id=1001, afk_channel=None),
        members=members,
        send=AsyncMock(),
        fetch_message=AsyncMock(),
    )
    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
    monkeypatch.setattr(
        guilds_service,
        "get_guild_settings",
        AsyncMock(return_value=SimpleNamespace(tracking_enabled=True)),
    )
    monkeypatch.setattr(
        guilds_service,
        "is_channel_excluded",
        AsyncMock(return_value=False),
    )
    party_reconcile = AsyncMock(
        return_value=VoicePartyResult(
            "1001",
            "2001",
            "continued",
            True,
            3,
            True,
            "9999",
            True,
            "tea_party",
            "tea_party",
        )
    )
    zen_reconcile = AsyncMock(
        return_value=VoiceZenResult(
            "1001",
            "2001",
            "inactive",
            False,
            None,
            0,
            0,
            (),
            None,
            None,
            False,
        )
    )
    monkeypatch.setattr(voice_party_service, "reconcile_voice_party", party_reconcile)
    monkeypatch.setattr(voice_zen_service, "reconcile_voice_zen", zen_reconcile)

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    await cog._reconcile_voice_party_channel(
        cast(discord.VoiceChannel | discord.StageChannel, channel)
    )

    assert party_reconcile.await_args is not None
    assert zen_reconcile.await_args is not None
    assert party_reconcile.await_args.kwargs["participant_ids"] == ["11", "12", "13"]
    assert zen_reconcile.await_args.kwargs["participant_ids"] == []


@pytest.mark.asyncio
async def test_reaction_to_old_bot_message_skips_received_with_fetch_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    @asynccontextmanager
    async def _fake_session_ctx() -> AsyncIterator[object]:
        yield session

    author = SimpleNamespace(
        id=3001,
        bot=True,
        name="old-bot",
        display_name="Old Bot",
        display_avatar=SimpleNamespace(url="https://example.invalid/bot.png"),
    )
    channel = SimpleNamespace(
        fetch_message=AsyncMock(return_value=SimpleNamespace(author=author))
    )
    guild = _Guild([])
    reactor = SimpleNamespace(
        id=2001,
        bot=False,
        guild=guild,
        display_name="alice",
        display_avatar=SimpleNamespace(url="https://example.invalid/a.png"),
    )
    payload = SimpleNamespace(
        guild_id=guild.id,
        channel_id=4001,
        message_id=5001,
        user_id=reactor.id,
        message_author_id=author.id,
        emoji="👍",
        member=reactor,
    )

    monkeypatch.setattr(tracking_mod, "async_session", _fake_session_ctx)
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
    record_reaction_add = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "src.cogs.tracking.reactions_service.record_reaction_add",
        record_reaction_add,
    )
    increment_given = AsyncMock()
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.increment_reactions_given",
        increment_given,
    )
    increment_received = AsyncMock()
    monkeypatch.setattr(
        "src.cogs.tracking.tracking_service.increment_reactions_received",
        increment_received,
    )
    monkeypatch.setattr(
        tracking_mod,
        "get_user_lifetime_levels",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.cogs.tracking.meta_service.get_user_bot_flag",
        AsyncMock(return_value=None),
    )
    upsert_meta = AsyncMock()
    monkeypatch.setattr("src.cogs.tracking.meta_service.upsert_user_meta", upsert_meta)

    def _get_channel(_channel_id: int) -> object:
        return channel

    bot = SimpleNamespace(get_channel=_get_channel)
    cog = TrackingCog(bot)  # type: ignore[arg-type]
    monkeypatch.setattr(cog, "_process_level_progress", AsyncMock())

    await cog._apply_reaction_delta(
        cast(discord.RawReactionActionEvent, payload), sign=+1
    )

    channel.fetch_message.assert_awaited_once_with(5001)
    record_reaction_add.assert_not_awaited()
    increment_given.assert_not_awaited()
    increment_received.assert_not_awaited()
    upsert_meta.assert_any_await(
        session,
        user_id="3001",
        display_name="Old Bot",
        avatar_url="https://example.invalid/bot.png",
        is_bot=True,
    )


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
async def test_grant_level_roles_stack_mode_adds_all_reached_without_removing() -> None:
    role11 = _Role(11)
    role12 = _Role(12)
    role21 = _Role(21)
    guild = _Guild([role11, role12, role21])

    member = SimpleNamespace(
        guild=guild,
        id=2001,
        roles=[role11],
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    rules = [
        LevelRoleAward(
            guild_id="1001", slot=1, grant_mode="stack", level=3, role_id="11"
        ),
        LevelRoleAward(
            guild_id="1001", slot=1, grant_mode="stack", level=10, role_id="12"
        ),
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
async def test_notify_level_up_sends_without_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "user_stats_site_base_url", "https://stats.example.com"
    )
    monkeypatch.setattr(settings, "user_stats_site_guild_id", "1001")
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
    view = place.send.await_args.kwargs["view"]
    labels = [_component_label(child) for child in view.children]
    urls = [getattr(child, "url", None) for child in view.children]
    assert "チル場所を設定" in labels
    assert "ユーザー統計を開く" in labels
    assert "https://stats.example.com/u/2001/level?days=30" in urls


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
        "src.cogs.tracking.tracking_service.add_voice_copresence_for_session_end",
        AsyncMock(),
    )
    finalize_bonus_mock = AsyncMock(return_value=0)
    monkeypatch.setattr(
        tracking_mod,
        "finalize_minecraft_voice_bonus",
        finalize_bonus_mock,
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
    finalize_bonus_mock.assert_awaited_once()
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
    checkpoint_mock = AsyncMock()
    monkeypatch.setattr(cog, "_checkpoint_active_voice_parties", checkpoint_mock)
    progress_mock = AsyncMock()
    monkeypatch.setattr(cog, "_process_level_progress", progress_mock)

    await cog._live_voice_level_loop()

    progress_mock.assert_awaited_once()
    checkpoint_mock.assert_awaited_once()
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
        "src.cogs.tracking.tracking_service.add_voice_copresence_for_session_end",
        AsyncMock(),
    )
    finalize_bonus_mock = AsyncMock(return_value=0)
    monkeypatch.setattr(
        tracking_mod,
        "finalize_minecraft_voice_bonus",
        finalize_bonus_mock,
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
    finalize_bonus_mock.assert_awaited_once()
    assert progress_mock.await_args is not None
    assert progress_mock.await_args.kwargs["prev_level"] == 2
    assert (str(guild.id), str(member.id)) not in cog._live_voice_level_cache
