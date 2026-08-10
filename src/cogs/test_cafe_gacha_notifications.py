from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.cogs import cafe_gacha as cafe_gacha_cog
from src.database.models import CafeGachaDraw, CafeGachaRedemption
from src.features.cafe_gacha import service as cafe_gacha_service
from src.features.cafe_gacha.catalog import rarity_label


class _FakeMessage:
    def __init__(
        self,
        *,
        message_id: int,
        content: str = "",
        embed: discord.Embed | None = None,
        nonce: str | int | None = None,
        fail_edits: int = 0,
    ) -> None:
        self.id = message_id
        self.content = content
        self.embeds = [embed] if embed is not None else []
        self.nonce = nonce
        self.author = SimpleNamespace(bot=True)
        self.edit_count = 0
        self.fail_edits = fail_edits
        self.attachment_filenames: list[str] = []
        self.view: discord.ui.View | None = None
        self.allowed_mentions: discord.AllowedMentions | None = None

    async def edit(self, **kwargs: Any) -> None:
        await asyncio.sleep(0)
        self.content = kwargs.get("content", self.content)
        embed = kwargs.get("embed", self.embeds[0] if self.embeds else None)
        if isinstance(embed, discord.Embed):
            self.embeds = [embed]
        elif embed is None:
            self.embeds = []
        self.edit_count += 1
        _close_discord_files(kwargs)
        if self.fail_edits > 0:
            self.fail_edits -= 1
            response = cast(
                Any,
                SimpleNamespace(status=500, reason="test failure", headers={}),
            )
            raise discord.HTTPException(response, "test failure")


def _close_discord_files(kwargs: dict[str, Any]) -> None:
    file = kwargs.get("file")
    if isinstance(file, discord.File):
        file.close()
    for key in ("files", "attachments"):
        values = kwargs.get(key, [])
        for value in values:
            if isinstance(value, discord.File):
                value.close()


class _FakeChannel:
    def __init__(
        self,
        *,
        first_message_id: int,
        fail_sends: int = 0,
        fail_edits: int = 0,
    ) -> None:
        self._next_message_id = first_message_id
        self.fail_sends = fail_sends
        self.fail_edits = fail_edits
        self.send_attempts = 0
        self.messages: list[_FakeMessage] = []

    async def send(self, content: str | None = None, **kwargs: Any) -> _FakeMessage:
        await asyncio.sleep(0)
        self.send_attempts += 1
        if self.fail_sends > 0:
            self.fail_sends -= 1
            response = cast(
                Any,
                SimpleNamespace(status=500, reason="test failure", headers={}),
            )
            raise discord.HTTPException(response, "test failure")
        message = _FakeMessage(
            message_id=self._next_message_id,
            content=content or "",
            embed=kwargs.get("embed"),
            nonce=kwargs.get("nonce"),
            fail_edits=self.fail_edits,
        )
        message.attachment_filenames = [
            file.filename
            for file in kwargs.get("files", [])
            if isinstance(file, discord.File)
        ]
        message.view = kwargs.get("view")
        message.allowed_mentions = kwargs.get("allowed_mentions")
        self.fail_edits = 0
        self._next_message_id += 1
        self.messages.append(message)
        _close_discord_files(kwargs)
        return message

    async def fetch_message(self, message_id: int) -> _FakeMessage:
        return next(message for message in self.messages if message.id == message_id)

    def history(
        self, *, limit: int | None, after: object
    ) -> AsyncIterator[_FakeMessage]:
        async def _iterate() -> AsyncIterator[_FakeMessage]:
            selected = self.messages if limit is None else self.messages[-limit:]
            for message in reversed(selected):
                yield message

        return _iterate()


async def _draw(
    db_session: AsyncSession,
    *,
    event_id: str,
    day: int = 9,
) -> CafeGachaDraw:
    result = await cafe_gacha_service.draw_card(
        db_session,
        event_id=event_id,
        guild_id="1001",
        user_id="2001",
        display_name="客",
        earned_xp=100,
        allow_paid=False,
        today=date(2026, 8, day),
        random_value=0,
    )
    assert result.draw is not None
    return result.draw


def _patch_delivery_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    counter: _FakeChannel,
    ledger: _FakeChannel,
) -> discord.Guild:
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)

    async def _channels(_guild: object) -> tuple[object, object]:
        return counter, ledger

    monkeypatch.setattr(cafe_gacha_cog, "async_session", factory)
    monkeypatch.setattr(cafe_gacha_cog, "_configured_channels", _channels)
    return cast(discord.Guild, SimpleNamespace(id=1001))


async def test_concurrent_draw_delivery_posts_photo_only_to_ledger(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-concurrent")
    counter = _FakeChannel(first_message_id=5001)
    ledger = _FakeChannel(first_message_id=6001)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    results = await asyncio.gather(
        cafe_gacha_cog._publish_draw(guild, draw),
        cafe_gacha_cog._publish_draw(guild, draw),
    )

    assert list(results) == [True, True]
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 1
    assert counter.messages == []
    assert len(ledger.messages) == 1
    assert ledger.messages[0].content == ""
    assert len(ledger.messages[0].embeds) == 1
    embed = ledger.messages[0].embeds[0]
    assert embed.title == f"{rarity_label(draw.rarity)}｜{draw.reward_name}"
    xp_balance = embed.fields[0].value or ""
    assert f"{draw.reward_xp:,} XP獲得" in xp_balance
    assert f"今回の収支 +{draw.reward_xp - draw.cost_xp:,} XP" in xp_balance
    assert "NEW" in xp_balance
    assert embed.description is not None
    assert "<@2001> さんが一枚引きました" in embed.description
    assert ledger.messages[0].allowed_mentions is not None
    assert ledger.messages[0].allowed_mentions.users is False
    assert ledger.messages[0].allowed_mentions.everyone is False
    assert ledger.messages[0].allowed_mentions.roles is False
    assert ledger.messages[0].allowed_mentions.replied_user is False
    assert draw.event_id not in str(embed.to_dict())
    assert embed.image.url == f"attachment://{draw.image_filename}"
    assert ledger.messages[0].attachment_filenames == [draw.image_filename]
    assert ledger.messages[0].view is None

    await db_session.refresh(draw)
    assert draw.counter_message_id is None
    assert draw.counter_completed_at is None
    assert draw.ledger_message_id == "6001"


async def test_draw_retry_sends_failed_ledger_notification_once(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-partial")
    counter = _FakeChannel(first_message_id=5101)
    ledger = _FakeChannel(first_message_id=6101, fail_sends=1)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    first = await cafe_gacha_cog._publish_draw(guild, draw)
    second = await cafe_gacha_cog._publish_draw(guild, draw)

    assert first is False
    assert second is True
    assert counter.send_attempts == 0
    assert counter.messages == []
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 1


async def test_draw_retry_recovers_orphan_ledger_post_by_hidden_nonce(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-orphan")
    counter = _FakeChannel(first_message_id=5201)
    ledger = _FakeChannel(first_message_id=6201)
    orphan = await ledger.send(
        embed=cafe_gacha_cog._result_embed(
            draw,
            owned_count=draw.owned_count,
            collected_count=draw.collected_count,
            with_image=False,
        ),
        nonce=cafe_gacha_cog._notification_nonce("draw", draw.event_id),
    )
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    published = await cafe_gacha_cog._publish_draw(guild, draw)

    assert published is True
    assert counter.send_attempts == 0
    assert counter.messages == []
    assert ledger.send_attempts == 1
    assert len(ledger.messages) == 1
    assert orphan.content == ""
    assert orphan.embeds[0].title == f"{rarity_label(draw.rarity)}｜{draw.reward_name}"
    assert draw.event_id not in str(orphan.embeds[0].to_dict())
    await db_session.refresh(draw)
    assert draw.ledger_message_id == str(orphan.id)


async def test_retry_pending_draw_does_not_post_to_counter(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-edit-retry")
    counter = _FakeChannel(first_message_id=5251)
    ledger = _FakeChannel(first_message_id=6251, fail_sends=1)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    first = await cafe_gacha_cog._publish_draw(guild, draw)
    await cafe_gacha_cog._retry_pending_notifications(guild)

    assert first is False
    assert counter.send_attempts == 0
    assert counter.messages == []
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 1
    await db_session.refresh(draw)
    assert draw.ledger_message_id == "6251"


async def test_concurrent_redemption_delivery_posts_only_to_ledger(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _draw(db_session, event_id="redemption-draw-1", day=9)
    await _draw(db_session, event_id="redemption-draw-2", day=10)
    result = await cafe_gacha_service.redeem_cards(
        db_session,
        event_id="redemption-concurrent",
        guild_id="1001",
        user_id="2001",
        display_name="客",
        quantities={"spent-tea": 1},
    )
    assert result.redemption is not None
    counter = _FakeChannel(first_message_id=5301)
    ledger = _FakeChannel(first_message_id=6301)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    await asyncio.gather(
        cafe_gacha_cog._publish_redemption(guild, result.redemption),
        cafe_gacha_cog._publish_redemption(guild, result.redemption),
    )

    assert counter.send_attempts == 0
    assert ledger.send_attempts == 1
    assert counter.messages == []
    assert len(ledger.messages) == 1
    assert ledger.messages[0].content == ""
    assert len(ledger.messages[0].embeds) == 1
    embed = ledger.messages[0].embeds[0]
    assert embed.title == "♻️ 重複カードをXP交換"
    assert embed.description is not None
    assert "<@2001>" in embed.description
    assert "**客**" not in embed.description
    assert "出がらし×1" in embed.description
    assert f"受取XP: {result.redemption.reward_xp:,} XP" in embed.description
    assert ledger.messages[0].allowed_mentions is not None
    assert ledger.messages[0].allowed_mentions.users is False
    assert ledger.messages[0].allowed_mentions.everyone is False
    assert ledger.messages[0].allowed_mentions.roles is False
    assert ledger.messages[0].allowed_mentions.replied_user is False
    assert result.redemption.event_id not in str(embed.to_dict())

    redemption = await db_session.get(CafeGachaRedemption, result.redemption.id)
    assert redemption is not None
    await db_session.refresh(redemption)
    assert redemption.counter_message_id is None
    assert redemption.ledger_message_id == "6301"


async def test_redemption_retry_sends_only_destination_that_failed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _draw(db_session, event_id="partial-redemption-draw-1", day=9)
    await _draw(db_session, event_id="partial-redemption-draw-2", day=10)
    result = await cafe_gacha_service.redeem_cards(
        db_session,
        event_id="redemption-partial",
        guild_id="1001",
        user_id="2001",
        display_name="客",
        quantities={"spent-tea": 1},
    )
    assert result.redemption is not None
    counter = _FakeChannel(first_message_id=5401)
    ledger = _FakeChannel(first_message_id=6401, fail_sends=1)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    await cafe_gacha_cog._publish_redemption(guild, result.redemption)
    await cafe_gacha_cog._publish_redemption(guild, result.redemption)

    assert counter.send_attempts == 0
    assert counter.messages == []
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 1


async def test_concurrent_setup_reuses_panel_after_first_config_commit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(cafe_gacha_cog, "async_session", factory)

    counter = cast(discord.TextChannel, SimpleNamespace(id=7101))
    ledger = cast(discord.TextChannel, SimpleNamespace(id=7102))
    panel = cast(discord.Message, SimpleNamespace(id=7201))
    panel_ids: list[str | None] = []

    async def _channel(
        _guild: discord.Guild, name: str, _configured_id: str | None = None
    ) -> discord.TextChannel:
        await asyncio.sleep(0)
        return counter if name == cafe_gacha_cog.COUNTER_NAME else ledger

    async def _panel(
        _guild: discord.Guild,
        _counter: discord.TextChannel,
        panel_message_id: str | None,
    ) -> discord.Message:
        panel_ids.append(panel_message_id)
        await asyncio.sleep(0)
        return panel

    monkeypatch.setattr(cafe_gacha_cog, "_find_or_create_channel", _channel)
    monkeypatch.setattr(cafe_gacha_cog, "_upsert_panel", _panel)
    guild = cast(discord.Guild, SimpleNamespace(id=1001))

    results = await asyncio.gather(
        cafe_gacha_cog._ensure_setup(guild, require_existing=False),
        cafe_gacha_cog._ensure_setup(guild, require_existing=False),
    )

    assert all(result == (counter, ledger) for result in results)
    assert panel_ids == [None, "7201"]
