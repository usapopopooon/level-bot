"""Tests for scheduled VC heatmap posts."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pytest

from src.cogs import daily_heatmap
from src.cogs.daily_heatmap import DailyHeatmapCog
from src.features.guilds.service import DailyHeatmapTarget
from src.features.stats import service as stats_service
from src.features.stats.service import HourlyActivityCell


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Bot:
    def get_guild(self, guild_id: int) -> object:
        return object()


class _Channel:
    def __init__(self) -> None:
        self.embed: Any | None = None
        self.file: Any | None = None

    async def send(self, *, embed: Any, file: Any) -> None:
        self.embed = embed
        self.file = file


@pytest.mark.asyncio
async def test_post_daily_heatmap_uses_fixed_recent_7_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _Channel()
    recorded: dict[str, object] = {}

    async def fake_get_hourly_activity_heatmap(
        _session: object,
        guild_id: str,
        *,
        days: int,
        end_date: date | None = None,
    ) -> list[HourlyActivityCell]:
        recorded["guild_id"] = guild_id
        recorded["days"] = days
        recorded["end_date"] = end_date
        return [
            HourlyActivityCell(
                weekday=5,
                hour=20,
                voice_seconds=300,
                active_users=1,
                intensity_percent=100,
            )
        ]

    async def fake_resolve_post_channel(
        _self: DailyHeatmapCog,
        _guild: object,
        channel_id: str,
    ) -> _Channel:
        recorded["channel_id"] = channel_id
        return channel

    monkeypatch.setattr(daily_heatmap, "async_session", _SessionContext)
    monkeypatch.setattr(
        stats_service,
        "get_hourly_activity_heatmap",
        fake_get_hourly_activity_heatmap,
    )
    monkeypatch.setattr(
        DailyHeatmapCog,
        "_resolve_post_channel",
        fake_resolve_post_channel,
    )
    monkeypatch.setattr(
        daily_heatmap,
        "render_hourly_activity_heatmap_table_png",
        lambda **_kwargs: BytesIO(b"png"),
    )

    cog = DailyHeatmapCog(_Bot())  # type: ignore[arg-type]
    target = DailyHeatmapTarget(
        guild_id="1001",
        channel_id="2001",
        days=365,
        post_time="00:00",
        timezone="Asia/Tokyo",
        last_posted_on=None,
    )

    posted = await cog._post_daily_heatmap(target, date(2026, 7, 4))

    assert posted is True
    assert recorded == {
        "channel_id": "2001",
        "guild_id": "1001",
        "days": 7,
        "end_date": date(2026, 7, 4),
    }
    assert channel.embed is not None
    assert channel.file is not None
    assert channel.embed.title == "直近７日間のVCアクティブヒートマップ🔥"
    assert channel.file.filename == "vc-active-heatmap-2026-07-04.png"
