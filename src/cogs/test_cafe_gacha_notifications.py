from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import discord
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.cogs import cafe_gacha as cafe_gacha_cog
from src.cogs import cafe_gacha_notifications
from src.cogs.cafe_gacha_common import CAFE_COLLECTION_SITE_URL
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
        embeds: list[discord.Embed] | None = None,
        nonce: str | int | None = None,
        fail_edits: int = 0,
    ) -> None:
        self.id = message_id
        self.content = content
        self.embeds = (
            embeds if embeds is not None else [embed] if embed is not None else []
        )
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
        fail_send_attempts: set[int] | None = None,
        fail_edits: int = 0,
    ) -> None:
        self._next_message_id = first_message_id
        self.fail_sends = fail_sends
        self.fail_send_attempts = fail_send_attempts or set()
        self.fail_edits = fail_edits
        self.send_attempts = 0
        self.messages: list[_FakeMessage] = []

    async def send(self, content: str | None = None, **kwargs: Any) -> _FakeMessage:
        await asyncio.sleep(0)
        self.send_attempts += 1
        if self.fail_sends > 0 or self.send_attempts in self.fail_send_attempts:
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
            embeds=kwargs.get("embeds"),
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


async def _ten_draws(
    db_session: AsyncSession, *, event_id: str
) -> tuple[CafeGachaDraw, ...]:
    result = await cafe_gacha_service.draw_cards(
        db_session,
        event_id=event_id,
        guild_id="1001",
        user_id="2001",
        display_name="客",
        earned_xp=0,
        count=10,
        today=date(2026, 8, 9),
        random_values=(0,) * 10,
    )
    assert result.status == "drawn"
    return result.draws


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

    monkeypatch.setattr(cafe_gacha_notifications, "async_session", factory)
    monkeypatch.setattr(cafe_gacha_notifications, "_configured_channels", _channels)
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
    assert ledger.send_attempts == 2
    assert counter.messages == []
    assert len(ledger.messages) == 2
    assert ledger.messages[0].content == ""
    assert len(ledger.messages[0].embeds) == 1
    embed = ledger.messages[0].embeds[0]
    assert embed.title == f"{rarity_label(draw.rarity)}｜{draw.reward_name}"
    assert embed.fields[0].name == f"🎉 +{draw.reward_xp - draw.cost_xp:,} XPの黒字！"
    xp_balance = embed.fields[0].value or ""
    assert f"{draw.reward_xp:,} XP獲得" in xp_balance
    assert "引くたび必ずプラス！" not in xp_balance
    assert "初入手" not in xp_balance
    assert "NEW COLLECTION" not in str(embed.to_dict())
    assert "新しいカード" not in str(embed.to_dict())
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
    assert ledger.messages[1].content == (
        f"✨ <@2001>さん、新しいカードを獲得しました！\n"
        f"📚 **{draw.reward_name}**がコレクションに加わりました！"
    )

    await db_session.refresh(draw)
    assert draw.counter_message_id is None
    assert draw.counter_completed_at is None
    assert draw.ledger_message_id == "6001"


@pytest.mark.parametrize(
    ("rarity", "was_duplicate", "expected_mentioned_rarity"),
    (
        ("C", True, None),
        ("UC", True, None),
        ("C", False, None),
        ("UC", False, None),
        ("R", True, "R"),
        ("SR", True, "SR"),
        ("SSR", True, "SSR"),
        ("UR", True, "UR"),
        ("MYTHIC", True, "幻"),
        ("R", False, "R"),
    ),
)
async def test_draw_delivery_mentions_user_after_result_for_rare_or_new(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rarity: str,
    was_duplicate: bool,
    expected_mentioned_rarity: str | None,
) -> None:
    draw = await _draw(
        db_session,
        event_id=f"draw-mention-{rarity.lower()}-{was_duplicate}",
    )
    draw.rarity = rarity
    draw.was_duplicate = was_duplicate
    if rarity == "UC" and not was_duplicate:
        draw.reward_name = "@everyone茶"
    await db_session.commit()
    counter = _FakeChannel(first_message_id=5011)
    ledger = _FakeChannel(first_message_id=6011)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    published = await cafe_gacha_cog._publish_draw(guild, draw)

    assert published is True
    assert counter.send_attempts == 0
    should_mention = expected_mentioned_rarity is not None or not was_duplicate
    assert len(ledger.messages) == (2 if should_mention else 1)
    assert len(ledger.messages[0].embeds) == 1
    assert ledger.messages[0].allowed_mentions is not None
    assert ledger.messages[0].allowed_mentions.users is False
    if not should_mention:
        return

    mention = ledger.messages[1]
    rare_notice = (
        "幻のカード"
        if rarity == "MYTHIC"
        else f"{expected_mentioned_rarity}以上のカード"
    )
    expected_lines = (
        [f"🎉 <@2001>さん、{rare_notice}を獲得しました！"]
        if expected_mentioned_rarity is not None
        else ["✨ <@2001>さん、新しいカードを獲得しました！"]
    )
    if not was_duplicate:
        prefix = "✨" if expected_mentioned_rarity is not None else "📚"
        safe_name = discord.utils.escape_mentions(
            discord.utils.escape_markdown(draw.reward_name)
        )
        expected_lines.append(f"{prefix} **{safe_name}**がコレクションに加わりました！")
    assert mention.content == "\n".join(expected_lines)
    assert "@here" not in mention.content
    assert "@everyone" not in mention.content
    assert "<@&" not in mention.content
    assert mention.embeds == []
    assert mention.nonce == cafe_gacha_cog._notification_nonce(
        "draw-rare-mention", draw.batch_id
    )
    assert mention.allowed_mentions is not None
    mentioned_users = mention.allowed_mentions.users
    assert not isinstance(mentioned_users, bool)
    assert [user.id for user in mentioned_users] == [2001]
    assert mention.allowed_mentions.everyone is False
    assert mention.allowed_mentions.roles is False
    assert mention.allowed_mentions.replied_user is False


async def test_concurrent_rare_draw_delivery_posts_one_result_then_one_mention(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-rare-concurrent")
    draw.rarity = "R"
    draw.was_duplicate = True
    await db_session.commit()
    counter = _FakeChannel(first_message_id=5021)
    ledger = _FakeChannel(first_message_id=6021)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    results = await asyncio.gather(
        cafe_gacha_cog._publish_draw(guild, draw),
        cafe_gacha_cog._publish_draw(guild, draw),
    )

    assert list(results) == [True, True]
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 2
    assert len(ledger.messages[0].embeds) == 1
    assert ledger.messages[1].content == (
        "🎉 <@2001>さん、R以上のカードを獲得しました！"
    )


async def test_ten_draw_delivery_posts_one_result_then_one_new_notification(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draws = await _ten_draws(db_session, event_id="draw-ten")
    draws[9].reward_key = draws[0].reward_key
    draws[9].reward_name = draws[0].reward_name
    draws[9].reward_description = draws[0].reward_description
    draws[9].image_filename = draws[0].image_filename
    await db_session.commit()
    counter = _FakeChannel(first_message_id=5051)
    ledger = _FakeChannel(first_message_id=6051)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    published = await cafe_gacha_cog._publish_draws(guild, draws)

    assert published is True
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 2
    message = ledger.messages[0]
    assert message.content == cafe_gacha_cog._batch_summary_content(draws)
    assert "最高 **N**" in message.content
    assert "NEW" not in message.content
    assert "新規登録" not in message.content
    assert draws[0].reward_name not in message.content
    assert message.attachment_filenames == [
        f"{index:02d}-{draw.image_filename}"
        for index, draw in enumerate(draws, start=1)
    ]
    assert len(message.embeds) == 10
    for index, (embed, draw) in enumerate(
        zip(message.embeds, draws, strict=True), start=1
    ):
        assert embed.title == (
            f"☕ 10枚まとめ {index}/10｜{rarity_label(draw.rarity)}｜{draw.reward_name}"
        )
        assert "NEW COLLECTION" not in str(embed.to_dict())
        assert "新しいカード" not in str(embed.to_dict())
        assert embed.image.url == f"attachment://{index:02d}-{draw.image_filename}"
        assert embed.url == (
            f"{CAFE_COLLECTION_SITE_URL}cards/{draw.reward_key}/?batch_slot={index}"
        )
        assert draw.event_id not in str(embed.to_dict())
    assert len({embed.url for embed in message.embeds}) == 10
    assert message.allowed_mentions is not None
    assert message.allowed_mentions.users is False
    assert ledger.messages[1].content == (
        f"✨ <@2001>さん、新しいカードを獲得しました！\n"
        f"📚 **{draws[0].reward_name}**がコレクションに加わりました！"
    )
    for draw in draws:
        await db_session.refresh(draw)
        assert draw.ledger_message_id == "6051"


async def test_ten_draw_delivery_mentions_once_after_results_when_rare_is_included(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draws = await _ten_draws(db_session, event_id="draw-ten-rare")
    draws[1].rarity = "SSR"
    draws[1].was_duplicate = False
    draws[1].reward_name = "玉露"
    draws[4].rarity = "SR"
    draws[4].was_duplicate = False
    draws[4].reward_name = "チャイ"
    draws[9].rarity = "R"
    await db_session.commit()
    counter = _FakeChannel(first_message_id=5056)
    ledger = _FakeChannel(first_message_id=6056)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    published = await cafe_gacha_cog._publish_draws(guild, draws)

    assert published is True
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 2
    assert len(ledger.messages[0].embeds) == 10
    assert ledger.messages[1].content == (
        "🎉 <@2001>さん、SSR以上のカードを獲得しました！\n"
        "✨ コレクションに新しいカードが **3枚** 加わりました！\n"
        f"📚 **{draws[0].reward_name}／玉露／チャイ**"
    )


async def test_ten_draw_retry_reuses_one_message_after_failed_api_request(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draws = await _ten_draws(db_session, event_id="draw-ten-retry")
    counter = _FakeChannel(first_message_id=5061)
    ledger = _FakeChannel(first_message_id=6061, fail_sends=1)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    first = await cafe_gacha_cog._publish_draws(guild, draws)
    second = await cafe_gacha_cog._publish_draws(guild, draws)

    assert first is False
    assert second is True
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 3
    assert len(ledger.messages) == 2
    assert len(ledger.messages[0].embeds) == 10
    assert len(ledger.messages[0].attachment_filenames) == 10
    assert "新しいカードを獲得しました" in ledger.messages[1].content
    for draw in draws:
        await db_session.refresh(draw)
        assert draw.ledger_message_id == "6061"


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
    assert ledger.send_attempts == 3
    assert len(ledger.messages) == 2
    assert "新しいカードを獲得しました" in ledger.messages[1].content


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
    assert ledger.send_attempts == 2
    assert len(ledger.messages) == 2
    assert orphan.content == ""
    assert orphan.embeds[0].title == f"{rarity_label(draw.rarity)}｜{draw.reward_name}"
    assert "新しいカードを獲得しました" in ledger.messages[1].content
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
    assert ledger.send_attempts == 3
    assert len(ledger.messages) == 2
    assert "新しいカードを獲得しました" in ledger.messages[1].content
    await db_session.refresh(draw)
    assert draw.ledger_message_id == "6251"


async def test_retry_pending_rare_draw_posts_result_then_mention(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-rare-retry")
    draw.rarity = "R"
    await db_session.commit()
    counter = _FakeChannel(first_message_id=5261)
    ledger = _FakeChannel(first_message_id=6261, fail_sends=1)
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    first = await cafe_gacha_cog._publish_draw(guild, draw)
    await cafe_gacha_cog._retry_pending_notifications(guild)

    assert first is False
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 3
    assert len(ledger.messages) == 2
    assert len(ledger.messages[0].embeds) == 1
    assert ledger.messages[1].content == (
        "🎉 <@2001>さん、R以上のカードを獲得しました！\n"
        f"✨ **{draw.reward_name}**がコレクションに加わりました！"
    )
    await db_session.refresh(draw)
    assert draw.ledger_message_id == "6261"


async def test_retry_pending_rare_mention_reuses_result_and_retries_only_mention(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw = await _draw(db_session, event_id="draw-rare-mention-retry")
    draw.rarity = "R"
    await db_session.commit()
    counter = _FakeChannel(first_message_id=5271)
    ledger = _FakeChannel(
        first_message_id=6271,
        fail_send_attempts={2},
    )
    guild = _patch_delivery_dependencies(monkeypatch, db_session, counter, ledger)

    first = await cafe_gacha_cog._publish_draw(guild, draw)
    await db_session.refresh(draw)
    ledger_id_after_failure = draw.ledger_message_id
    await cafe_gacha_cog._retry_pending_notifications(guild)

    assert first is True
    assert ledger_id_after_failure is None
    assert counter.send_attempts == 0
    assert ledger.send_attempts == 3
    assert len(ledger.messages) == 2
    assert len(ledger.messages[0].embeds) == 1
    assert ledger.messages[1].content == (
        "🎉 <@2001>さん、R以上のカードを獲得しました！\n"
        f"✨ **{draw.reward_name}**がコレクションに加わりました！"
    )
    await db_session.refresh(draw)
    assert draw.ledger_message_id == "6271"


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
    assert embed.title == "♻️ 重複カード交換でXPボーナス！"
    assert embed.description is not None
    assert "<@2001>" in embed.description
    assert "**客**" not in embed.description
    assert "出がらし×1" in embed.description
    assert f"🎉 +{result.redemption.reward_xp:,} XPを追加獲得！" in embed.description
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


async def test_concurrent_setup_reuses_panel_without_posting_leaderboard(
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
    upsert_leaderboard = AsyncMock()
    monkeypatch.setattr(
        cafe_gacha_cog,
        "upsert_cafe_leaderboard_panel",
        upsert_leaderboard,
    )
    guild = cast(discord.Guild, SimpleNamespace(id=1001))

    results = await asyncio.gather(
        cafe_gacha_cog._ensure_setup(guild, require_existing=False),
        cafe_gacha_cog._ensure_setup(guild, require_existing=False),
    )

    assert all(result == (counter, ledger) for result in results)
    assert panel_ids == [None, "7201"]
    upsert_leaderboard.assert_not_awaited()
