"""Reusable buttons for level-related Discord responses."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

import discord
from discord.ext import commands

from src.config import settings
from src.database.engine import async_session
from src.features.chill import service as chill_service
from src.features.chill.presets import (
    format_chill_choice_name,
    format_chill_place_name,
)

logger = logging.getLogger(__name__)

CHILL_PLACE_BUTTON_LABEL = "チル場所を設定"
USER_STATS_BUTTON_LABEL = "ユーザー統計を開く"
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


async def fetch_chill_place_options(
    guild_id: int,
    user_id: int,
) -> tuple[ChillPlaceOptions | None, str | None]:
    try:
        async with async_session() as session:
            options = await chill_service.get_chill_place_options(
                session,
                str(guild_id),
                str(user_id),
            )
    except chill_service.ChillLevelUnavailableError:
        return (
            None,
            "現在レベルを取得できませんでした。少し待ってから再度お試しください。",
        )
    except Exception:
        logger.exception(
            "Failed to fetch chill places from level DB guild=%s user=%s",
            guild_id,
            user_id,
        )
        return None, "チル場所の取得に失敗しました。少し待ってから再度お試しください。"

    places = tuple(
        ChillPlaceOption(
            required_level=place.required_level,
            label=format_chill_choice_name(place),
            display_name=format_chill_place_name(place),
            description=place.description,
            selected=place.required_level == options.selected_required_level,
        )
        for place in options.places
    )
    return (
        ChillPlaceOptions(
            level=options.level.level,
            selected_required_level=options.selected_required_level,
            places=places,
        ),
        None,
    )


async def set_level_chill_place(
    guild_id: int,
    user_id: int,
    required_level: int,
) -> tuple[str | None, str | None]:
    try:
        async with async_session() as session:
            selection = await chill_service.set_user_chill_place(
                session,
                str(guild_id),
                str(user_id),
                required_level,
            )
    except chill_service.LockedChillPlaceError:
        return None, "そのチル場所は現在レベルではまだ未解放です。"
    except chill_service.ChillLevelUnavailableError:
        return (
            None,
            "現在レベルを取得できませんでした。少し待ってから再度お試しください。",
        )
    except chill_service.UnknownChillPlaceError:
        return None, "そのチル場所は設定されていません。"
    except Exception:
        logger.exception(
            "Failed to set chill place in level DB guild=%s user=%s level=%s",
            guild_id,
            user_id,
            required_level,
        )
        return None, "チル場所の設定に失敗しました。少し待ってから再度お試しください。"

    return format_chill_place_name(selection.selected), None


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
        selected_name, error = await set_level_chill_place(
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
    """Persistent button that opens the chill-place selector."""

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
