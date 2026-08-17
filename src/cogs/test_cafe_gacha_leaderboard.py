from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import discord
import pytest

from src.cogs import cafe_gacha_leaderboard as leaderboard_ui
from src.features.cafe_gacha import leaderboard as leaderboard_service
from src.features.feature_access.service import CAFE_GACHA


def _entry(
    user_id: str,
    *,
    collection_count: int,
    mastery_score: int | None = None,
) -> leaderboard_service.CafeLeaderboardEntry:
    return leaderboard_service.CafeLeaderboardEntry(
        user_id=user_id,
        collection_count=collection_count,
        total_draws=collection_count,
        mastery_score=mastery_score or collection_count,
        discovery_cards=collection_count,
        familiar_cards=0,
        regular_cards=0,
        signature_cards=0,
        completed_sets=0,
        rare_collection_count=0,
        rare_r_count=0,
        rare_sr_count=0,
        rare_ssr_count=0,
        n_collection_count=collection_count,
        n_mastery_score=mastery_score or collection_count,
        n_signature_cards=0,
    )


def _cached_snapshot(count: int = 21) -> leaderboard_ui.CachedCafeLeaderboard:
    return leaderboard_ui.CachedCafeLeaderboard(
        snapshot=leaderboard_service.CafeLeaderboardSnapshot(
            entries=tuple(
                _entry(str(2000 + index), collection_count=count - index + 1)
                for index in range(1, count + 1)
            )
        ),
        captured_at=datetime(2026, 8, 17, 9, 30, tzinfo=UTC),
        monotonic_at=100.0,
    )


def test_public_panel_shows_only_top_five_collection_entries() -> None:
    embed = leaderboard_ui.build_cafe_leaderboard_panel_embed(_cached_snapshot())
    rendered = str(embed.to_dict())

    assert embed.title == leaderboard_ui.LEADERBOARD_PANEL_TITLE
    assert "<@2001>" in rendered
    assert "<@2005>" in rendered
    assert "<@2006>" not in rendered
    assert "全120種" in rendered
    assert "最大5分間キャッシュ" in (embed.footer.text or "")


def test_private_detail_shows_top_twenty_and_viewers_own_rank() -> None:
    embed = leaderboard_ui.build_cafe_leaderboard_detail_embed(
        _cached_snapshot(),
        category="collection",
        viewer_id="2021",
    )
    rendered = str(embed.to_dict())

    assert "<@2001>" in rendered
    assert "<@2020>" in rendered
    assert "<@2021>" not in (embed.description or "")
    own_field = next(field for field in embed.fields if field.name == "あなたの順位")
    assert own_field.value is not None
    assert "#21" in own_field.value
    assert "<@2021>" in own_field.value


async def test_leaderboard_panel_has_five_distinct_category_buttons() -> None:
    view = leaderboard_ui.CafeLeaderboardPanelView(123456)
    buttons = [
        child.item
        for child in view.children
        if isinstance(child, discord.ui.DynamicItem)
    ]

    assert [button.label for button in buttons] == [
        "図鑑",
        "熟練度",
        "セット",
        "レア棚",
        "ネタ棚",
    ]
    assert [button.custom_id for button in buttons] == [
        "level:cafe:leaderboard:collection:123456",
        "level:cafe:leaderboard:mastery:123456",
        "level:cafe:leaderboard:sets:123456",
        "level:cafe:leaderboard:rare:123456",
        "level:cafe:leaderboard:joke:123456",
    ]


async def test_leaderboard_snapshot_is_loaded_at_most_once_per_five_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaderboard_ui.clear_cafe_leaderboard_cache()
    snapshot = _cached_snapshot().snapshot
    read_snapshot = AsyncMock(return_value=snapshot)
    moments = iter((100.0, 399.0, 401.0))
    monkeypatch.setattr(leaderboard_ui, "_read_leaderboard_snapshot", read_snapshot)
    monkeypatch.setattr(leaderboard_ui, "monotonic", lambda: next(moments))

    first, first_refreshed = await leaderboard_ui.get_cached_cafe_leaderboard(1001)
    second, second_refreshed = await leaderboard_ui.get_cached_cafe_leaderboard(1001)
    third, third_refreshed = await leaderboard_ui.get_cached_cafe_leaderboard(1001)

    assert first is second
    assert third is not second
    assert (first_refreshed, second_refreshed, third_refreshed) == (True, False, True)
    assert read_snapshot.await_count == 2


async def test_category_button_refreshes_public_panel_and_replies_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = _cached_snapshot()
    access = AsyncMock(return_value=True)
    response = SimpleNamespace(defer=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    message = SimpleNamespace(edit=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=SimpleNamespace(id=2001),
            response=response,
            followup=followup,
            message=message,
        ),
    )
    monkeypatch.setattr(leaderboard_ui, "ensure_feature_access", access)
    monkeypatch.setattr(
        leaderboard_ui,
        "get_cached_cafe_leaderboard",
        AsyncMock(return_value=(cached, True)),
    )

    await leaderboard_ui.DynamicCafeLeaderboardButton(1001, "rare").callback(
        interaction
    )

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=CAFE_GACHA,
    )
    response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    message.edit.assert_awaited_once()
    edit_kwargs: dict[str, Any] = message.edit.await_args.kwargs
    assert edit_kwargs["allowed_mentions"].users is False
    assert edit_kwargs["allowed_mentions"].roles is False
    assert edit_kwargs["allowed_mentions"].everyone is False
    followup.send.assert_awaited_once()
    send_kwargs: dict[str, Any] = followup.send.await_args.kwargs
    assert send_kwargs["ephemeral"] is True
    assert send_kwargs["allowed_mentions"].users is False
    assert send_kwargs["allowed_mentions"].roles is False
    assert send_kwargs["allowed_mentions"].everyone is False
    assert "レア棚ランキング" in send_kwargs["embed"].title


class _FakeLeaderboardMessage:
    def __init__(self, message_id: int, embed: discord.Embed) -> None:
        self.id = message_id
        self.author = SimpleNamespace(bot=True)
        self.content = ""
        self.embeds = [embed]
        self.edit = AsyncMock()


class _FakeLeaderboardChannel:
    def __init__(self) -> None:
        self.messages: list[_FakeLeaderboardMessage] = []
        self.send = AsyncMock(side_effect=self._send)

    async def _send(self, **kwargs: Any) -> _FakeLeaderboardMessage:
        message = _FakeLeaderboardMessage(len(self.messages) + 1, kwargs["embed"])
        self.messages.append(message)
        return message

    def history(self, *, limit: int | None) -> Any:
        assert limit is None

        async def _iterate() -> Any:
            for message in reversed(self.messages):
                yield message

        return _iterate()

    async def fetch_message(self, message_id: int) -> _FakeLeaderboardMessage:
        return next(message for message in self.messages if message.id == message_id)


async def test_leaderboard_panel_reuses_saved_message_instead_of_reposting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _FakeLeaderboardChannel()
    cached = _cached_snapshot()
    monkeypatch.setattr(
        leaderboard_ui,
        "get_cached_cafe_leaderboard",
        AsyncMock(return_value=(cached, False)),
    )

    first = cast(
        _FakeLeaderboardMessage,
        await leaderboard_ui.upsert_cafe_leaderboard_panel(
            cast(discord.TextChannel, channel),
            guild_id=1001,
            panel_message_id=None,
        ),
    )
    second = cast(
        _FakeLeaderboardMessage,
        await leaderboard_ui.upsert_cafe_leaderboard_panel(
            cast(discord.TextChannel, channel),
            guild_id=1001,
            panel_message_id=str(first.id),
        ),
    )

    assert second is first
    assert channel.send.await_count == 1
    first.edit.assert_awaited_once()
    edit_call = first.edit.await_args
    assert edit_call is not None
    assert edit_call.kwargs["content"] is None
    assert isinstance(
        edit_call.kwargs["view"],
        leaderboard_ui.CafeLeaderboardPanelView,
    )
