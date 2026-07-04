"""Reusable buttons for level-related Discord responses."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import discord
import httpx
from discord.ext import commands

from src.config import settings

logger = logging.getLogger(__name__)

CHILL_PLACE_BUTTON_LABEL = "チル場所を設定"
USER_STATS_BUTTON_LABEL = "ユーザー統計を開く"
INTRO_API_TIMEOUT_SECONDS = 8.0
MAX_SELECT_OPTIONS = 25


@dataclass(frozen=True)
class ChillPlaceOption:
    required_level: int
    label: str
    display_name: str
    description: str | None
    selected: bool = False


@dataclass(frozen=True)
class ChillPlaceOptions:
    level: int
    selected_required_level: int | None
    places: tuple[ChillPlaceOption, ...]


def build_user_stats_url(guild_id: str, user_id: int) -> str | None:
    stats_base_url = settings.user_stats_site_base_url.strip().rstrip("/")
    stats_guild_id = settings.user_stats_site_guild_id.strip()
    if not stats_base_url or not stats_guild_id:
        logger.info(
            "Skip user stats link: USER_STATS_SITE_GUILD_ID or "
            "USER_STATS_SITE_BASE_URL is unset guild=%s user=%s "
            "has_guild_id=%s has_base_url=%s",
            guild_id,
            user_id,
            bool(stats_guild_id),
            bool(stats_base_url),
        )
        return None
    if guild_id != stats_guild_id:
        logger.info(
            "Skip user stats link: guild mismatch guild=%s configured_guild=%s user=%s",
            guild_id,
            stats_guild_id,
            user_id,
        )
        return None

    base_url = stats_base_url.removesuffix("/u")
    stats_url = f"{base_url}/u/{user_id}/level?days=30"
    logger.info(
        "Add user stats link guild=%s user=%s url=%s",
        guild_id,
        user_id,
        stats_url,
    )
    return stats_url


def intro_api_is_configured() -> bool:
    return bool(settings.intro_api_base_url.strip() and settings.intro_api_key.strip())


def build_intro_api_url(guild_id: int, user_id: int, suffix: str) -> str:
    base_url = settings.intro_api_base_url.strip().rstrip("/")
    return f"{base_url}/api/v1/guilds/{guild_id}/users/{user_id}/{suffix}"


def build_intro_api_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.intro_api_key.strip()}"}


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_chill_place_option(
    raw: object,
    selected_required_level: int | None,
) -> ChillPlaceOption | None:
    if not isinstance(raw, dict):
        return None
    required_level = raw.get("required_level")
    if not isinstance(required_level, int) or isinstance(required_level, bool):
        return None

    display_name = _string_or_none(raw.get("display_name"))
    if display_name is None:
        name = _string_or_none(raw.get("name")) or f"Lv.{required_level}"
        emoji = _string_or_none(raw.get("emoji"))
        display_name = f"{emoji} {name}" if emoji else name

    label = _string_or_none(raw.get("choice_label")) or (
        f"{display_name} (Lv.{required_level})"
    )
    return ChillPlaceOption(
        required_level=required_level,
        label=label,
        display_name=display_name,
        description=_string_or_none(raw.get("description")),
        selected=required_level == selected_required_level,
    )


def _parse_chill_place_options(data: Any) -> ChillPlaceOptions | None:
    if not isinstance(data, dict):
        return None
    level = data.get("level", {}).get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        return None
    selected_required_level = data.get("selected_required_level")
    if not isinstance(selected_required_level, int):
        selected_required_level = None

    raw_places = data.get("places")
    if not isinstance(raw_places, list):
        return None
    places = tuple(
        option
        for option in (
            _parse_chill_place_option(raw, selected_required_level)
            for raw in raw_places
        )
        if option is not None
    )
    return ChillPlaceOptions(
        level=level,
        selected_required_level=selected_required_level,
        places=places,
    )


async def fetch_chill_place_options(
    guild_id: int,
    user_id: int,
) -> tuple[ChillPlaceOptions | None, str | None]:
    if not intro_api_is_configured():
        return (
            None,
            "intro-bot API 連携が未設定です。`/intro-chill set` から変更してください。",
        )

    url = build_intro_api_url(guild_id, user_id, "chill-places")
    try:
        async with httpx.AsyncClient(timeout=INTRO_API_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=build_intro_api_headers())
    except httpx.HTTPError:
        logger.exception(
            "Failed to fetch chill places guild=%s user=%s",
            guild_id,
            user_id,
        )
        return None, "チル場所の取得に失敗しました。少し待ってから再度お試しください。"

    if response.status_code == 424:
        return (
            None,
            "現在レベルを取得できませんでした。少し待ってから再度お試しください。",
        )
    if response.status_code == 401:
        logger.warning("intro-bot API auth failed while fetching chill places")
        return None, "intro-bot API の認証に失敗しました。管理者に確認してください。"
    if response.status_code >= 400:
        logger.warning(
            "intro-bot API returned %s while fetching chill places guild=%s user=%s",
            response.status_code,
            guild_id,
            user_id,
        )
        return None, "チル場所の取得に失敗しました。少し待ってから再度お試しください。"

    try:
        data = response.json()
    except ValueError:
        logger.warning("intro-bot API returned invalid JSON for chill places")
        return None, "チル場所の取得に失敗しました。少し待ってから再度お試しください。"

    options = _parse_chill_place_options(data)
    if options is None:
        logger.warning("intro-bot API returned unexpected chill place payload")
        return None, "チル場所の取得に失敗しました。少し待ってから再度お試しください。"
    return options, None


def _selected_display_name(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    selected = data.get("selected")
    if not isinstance(selected, dict):
        return None
    return _string_or_none(selected.get("display_name")) or _string_or_none(
        selected.get("name")
    )


async def set_intro_chill_place(
    guild_id: int,
    user_id: int,
    required_level: int,
) -> tuple[str | None, str | None]:
    if not intro_api_is_configured():
        return (
            None,
            "intro-bot API 連携が未設定です。`/intro-chill set` から変更してください。",
        )

    url = build_intro_api_url(guild_id, user_id, "chill-place")
    try:
        async with httpx.AsyncClient(timeout=INTRO_API_TIMEOUT_SECONDS) as client:
            response = await client.put(
                url,
                headers=build_intro_api_headers(),
                json={"required_level": required_level},
            )
    except httpx.HTTPError:
        logger.exception(
            "Failed to set chill place guild=%s user=%s level=%s",
            guild_id,
            user_id,
            required_level,
        )
        return None, "チル場所の設定に失敗しました。少し待ってから再度お試しください。"

    if response.status_code == 403:
        return None, "そのチル場所は現在レベルではまだ未解放です。"
    if response.status_code == 424:
        return (
            None,
            "現在レベルを取得できませんでした。少し待ってから再度お試しください。",
        )
    if response.status_code == 401:
        logger.warning("intro-bot API auth failed while setting chill place")
        return None, "intro-bot API の認証に失敗しました。管理者に確認してください。"
    if response.status_code >= 400:
        logger.warning(
            "intro-bot API returned %s while setting chill place guild=%s user=%s",
            response.status_code,
            guild_id,
            user_id,
        )
        return None, "チル場所の設定に失敗しました。少し待ってから再度お試しください。"

    try:
        selected_name = _selected_display_name(response.json())
    except ValueError:
        selected_name = None
    return selected_name, None


def _select_option_description(option: ChillPlaceOption) -> str | None:
    if option.description is None:
        return None
    return option.description[:100]


def build_chill_place_select_options(
    places: Iterable[ChillPlaceOption],
) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label=place.label[:100],
            value=str(place.required_level),
            description=_select_option_description(place),
            default=place.selected,
        )
        for place in tuple(places)[:MAX_SELECT_OPTIONS]
    ]


class ChillPlaceSelect(discord.ui.Select[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        places: tuple[ChillPlaceOption, ...],
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        super().__init__(
            placeholder="自己紹介に表示するチル場所を選択",
            min_values=1,
            max_values=1,
            options=build_chill_place_select_options(places),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このチル場所を設定できるのは本人だけです。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        selected_level = int(self.values[0])
        selected_name, error = await set_intro_chill_place(
            self.guild_id,
            self.user_id,
            selected_level,
        )
        if error is not None:
            await interaction.followup.send(error, ephemeral=True)
            return

        name = selected_name or f"Lv.{selected_level}"
        await interaction.followup.send(
            f"チル場所を「{name}」に設定しました。",
            ephemeral=True,
        )


class ChillPlaceSelectView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        places: tuple[ChillPlaceOption, ...],
    ) -> None:
        super().__init__()
        self.add_item(ChillPlaceSelect(guild_id, user_id, places))


class DynamicChillPlaceButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:chill:set:(?P<guild_id>\d+):(?P<user_id>\d+)",
):
    """Persistent button that opens the intro-bot chill-place selector."""

    def __init__(self, guild_id: int, user_id: int) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        super().__init__(
            discord.ui.Button(
                label=CHILL_PLACE_BUTTON_LABEL,
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:chill:set:{guild_id}:{user_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicChillPlaceButton:
        return cls(guild_id=int(match["guild_id"]), user_id=int(match["user_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このチル場所を設定できるのは本人だけです。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        options, error = await fetch_chill_place_options(self.guild_id, self.user_id)
        if error is not None:
            await interaction.followup.send(error, ephemeral=True)
            return
        if options is None or not options.places:
            await interaction.followup.send(
                "選択できるチル場所がまだありません。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "自己紹介に表示するチル場所を選んでください。",
            view=ChillPlaceSelectView(self.guild_id, self.user_id, options.places),
            ephemeral=True,
        )


class LevelActionView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, stats_url: str | None) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicChillPlaceButton(guild_id, user_id))
        if stats_url is not None:
            self.add_item(
                discord.ui.Button(label=USER_STATS_BUTTON_LABEL, url=stats_url)
            )


def build_level_action_view(
    guild_id: str | int,
    user_id: int,
    stats_url: str | None,
) -> discord.ui.View:
    return LevelActionView(int(guild_id), user_id, stats_url)


def register_level_action_dynamic_items(bot: commands.Bot) -> None:
    bot.add_dynamic_items(DynamicChillPlaceButton)
