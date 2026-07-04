"""Slash commands for chill-place selection and configuration."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from src.database.engine import async_session
from src.features.chill import service as chill_service
from src.features.chill.presets import (
    ChillDisplay,
    ChillPlace,
    format_chill_choice_name,
    format_chill_place_name,
)

logger = logging.getLogger(__name__)

DISCORD_MESSAGE_LIMIT = 2000
MAX_CHOICES = 25


@dataclass(frozen=True)
class ChillCommandContext:
    level: int
    progress: float
    selected_required_level: int | None
    places: tuple[ChillPlace, ...]
    unlocked_places: tuple[ChillPlace, ...]
    display: ChillDisplay | None


def truncate(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_chill_display(display: ChillDisplay) -> str:
    lines: list[str] = []
    if display.current is not None:
        lines.append(
            f"{format_chill_place_name(display.current)} "
            f"(Lv.{display.current.required_level})"
        )
        if display.current.tags:
            lines.append(" / ".join(display.current.tags))
        if display.current.description:
            lines.append(display.current.description)
    else:
        lines.append("まだ解放されていません")
    if display.next_place is not None:
        lines.append(
            "次の解放: "
            f"{format_chill_place_name(display.next_place)} "
            f"Lv.{display.next_place.required_level}"
        )
    if display.selected_locked:
        lines.append("選択中の場所は現在レベルでは未解放です")
    return "\n".join(lines)


def format_chill_list(places: Iterable[ChillPlace], level: int | None = None) -> str:
    lines: list[str] = []
    for place in places:
        if level is None:
            prefix = "-"
        elif place.required_level <= level:
            prefix = "✓"
        else:
            prefix = "□"
        lines.append(
            f"{prefix} Lv.{place.required_level} {format_chill_place_name(place)}"
        )
    return "\n".join(lines)


def resolve_chill_place_selection(
    places: Iterable[ChillPlace],
    value: str,
) -> ChillPlace | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit():
        required_level = int(raw)
        return next(
            (place for place in places if place.required_level == required_level),
            None,
        )

    normalized = raw.casefold()
    for place in places:
        names = (
            place.name,
            format_chill_place_name(place),
            format_chill_choice_name(place),
        )
        if normalized in {name.casefold() for name in names}:
            return place
    return None


def build_chill_place_choices(
    places: Iterable[ChillPlace],
    current: str,
) -> list[app_commands.Choice[str]]:
    query = current.strip().casefold()
    choices: list[app_commands.Choice[str]] = []
    for place in places:
        label = format_chill_choice_name(place)
        if (
            query
            and query not in label.casefold()
            and query not in place.name.casefold()
        ):
            continue
        choices.append(
            app_commands.Choice(
                name=label[:100],
                value=str(place.required_level),
            )
        )
        if len(choices) >= MAX_CHOICES:
            break
    return choices


async def fetch_chill_context(
    guild_id: int,
    user_id: int,
) -> tuple[ChillCommandContext | None, str | None]:
    try:
        async with async_session() as session:
            options = await chill_service.get_chill_place_options(
                session,
                str(guild_id),
                str(user_id),
            )
            places = await chill_service.list_chill_places(session, str(guild_id))
    except chill_service.ChillLevelUnavailableError:
        return (
            None,
            "現在レベルを取得できませんでした。少し待ってから再度お試しください。",
        )
    except Exception:
        logger.exception(
            "Failed to fetch chill context guild=%s user=%s",
            guild_id,
            user_id,
        )
        return None, "チル場所の取得に失敗しました。少し待ってから再度お試しください。"

    return (
        ChillCommandContext(
            level=options.level.level,
            progress=options.level.progress,
            selected_required_level=options.selected_required_level,
            places=places,
            unlocked_places=options.places,
            display=options.display,
        ),
        None,
    )


class ChillCommandsCog(commands.Cog):
    """Commands for user-facing and admin chill-place workflows."""

    chill_group = app_commands.Group(
        name="level-chill",
        description="自己紹介に表示するチル場所を選択",
        guild_only=True,
    )
    chill_config_group = app_commands.Group(
        name="level-chill-config",
        description="レベルごとのチル場所を管理",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @chill_group.command(
        name="list",
        description="レベルごとのチル場所と自分の解放状況を表示",
    )
    async def chill_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        context, error = await fetch_chill_context(
            interaction.guild_id,
            interaction.user.id,
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert context is not None
        text = truncate(format_chill_list(context.places, level=context.level))
        await interaction.response.send_message(text, ephemeral=True)

    async def chill_place_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild_id is None:
            return []
        context, error = await fetch_chill_context(
            interaction.guild_id,
            interaction.user.id,
        )
        if error is not None or context is None:
            return []
        return build_chill_place_choices(context.unlocked_places, current)

    @chill_group.command(name="set", description="自己紹介に表示するチル場所を選択")
    @app_commands.describe(place="チル場所の名前")
    @app_commands.autocomplete(place=chill_place_autocomplete)
    async def chill_set(
        self,
        interaction: discord.Interaction,
        place: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        context, error = await fetch_chill_context(
            interaction.guild_id,
            interaction.user.id,
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert context is not None
        selected = resolve_chill_place_selection(context.places, place)
        if selected is None:
            await interaction.response.send_message(
                "そのチル場所は設定されていません。候補から場所名を選んでください。",
                ephemeral=True,
            )
            return

        try:
            async with async_session() as session:
                selection = await chill_service.set_user_chill_place(
                    session,
                    str(interaction.guild_id),
                    str(interaction.user.id),
                    selected.required_level,
                )
        except chill_service.LockedChillPlaceError:
            await interaction.response.send_message(
                (
                    f"{selected.name} は Lv.{selected.required_level} で解放されます。"
                    f"現在は Lv.{context.level} です。"
                ),
                ephemeral=True,
            )
            return
        except chill_service.ChillLevelUnavailableError:
            await interaction.response.send_message(
                "現在レベルを取得できませんでした。少し待ってから再度お試しください。",
                ephemeral=True,
            )
            return
        except chill_service.UnknownChillPlaceError:
            await interaction.response.send_message(
                "そのチル場所は設定されていません。",
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception(
                "Failed to set chill place guild=%s user=%s level=%s",
                interaction.guild_id,
                interaction.user.id,
                selected.required_level,
            )
            await interaction.response.send_message(
                "チル場所の設定に失敗しました。少し待ってから再度お試しください。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"チル場所を「{format_chill_place_name(selection.selected)}」に設定しました。",
            ephemeral=True,
        )

    @chill_group.command(name="clear", description="チル場所の選択を解除")
    async def chill_clear(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        try:
            async with async_session() as session:
                await chill_service.clear_user_chill_place(
                    session,
                    str(interaction.guild_id),
                    str(interaction.user.id),
                )
        except Exception:
            logger.exception(
                "Failed to clear chill place guild=%s user=%s",
                interaction.guild_id,
                interaction.user.id,
            )
            await interaction.response.send_message(
                "チル場所の解除に失敗しました。少し待ってから再度お試しください。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "チル場所の選択を解除しました。現在レベルで解放済みの一番上の場所を自動表示します。",
            ephemeral=True,
        )

    @chill_group.command(name="mine", description="現在のチル場所を表示")
    async def chill_mine(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        context, error = await fetch_chill_context(
            interaction.guild_id,
            interaction.user.id,
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        assert context is not None
        if context.display is None:
            await interaction.response.send_message(
                "現在レベルを取得できませんでした。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            format_chill_display(context.display),
            ephemeral=True,
        )

    @chill_config_group.command(
        name="add",
        description="レベルごとのチル場所を追加・変更",
    )
    @app_commands.describe(
        level="解放レベル",
        name="場所名",
        emoji="表示する絵文字。標準絵文字推奨",
    )
    async def chill_place_add(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 1, 1000],
        name: app_commands.Range[str, 1, 80],
        emoji: app_commands.Range[str, 1, 40] | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        clean_name = name.strip()
        clean_emoji = emoji.strip() if emoji is not None else None
        if clean_emoji == "":
            clean_emoji = None
        if not clean_name:
            await interaction.response.send_message(
                "場所名を入力してください。",
                ephemeral=True,
            )
            return

        try:
            async with async_session() as session:
                await chill_service.upsert_guild_chill_place(
                    session,
                    str(interaction.guild_id),
                    level,
                    clean_name,
                    clean_emoji,
                )
                places = await chill_service.list_chill_places(
                    session,
                    str(interaction.guild_id),
                )
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        except Exception:
            logger.exception(
                "Failed to upsert guild chill place guild=%s level=%s",
                interaction.guild_id,
                level,
            )
            await interaction.response.send_message(
                "更新に失敗しました。",
                ephemeral=True,
            )
            return

        place = next(place for place in places if place.required_level == level)
        await interaction.response.send_message(
            (
                f"Lv.{level} のチル場所を"
                f"「{format_chill_place_name(place)}」に設定しました。"
            ),
            ephemeral=True,
        )

    @chill_config_group.command(
        name="remove",
        description="追加・変更したチル場所を削除",
    )
    @app_commands.describe(level="削除する解放レベル")
    async def chill_place_remove(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 1, 1000],
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        try:
            async with async_session() as session:
                removed = await chill_service.remove_guild_chill_place(
                    session,
                    str(interaction.guild_id),
                    level,
                )
        except Exception:
            logger.exception(
                "Failed to remove guild chill place guild=%s level=%s",
                interaction.guild_id,
                level,
            )
            await interaction.response.send_message(
                "更新に失敗しました。",
                ephemeral=True,
            )
            return

        if not removed:
            await interaction.response.send_message(
                "カスタム設定はありませんでした。プリセットの場所はそのまま表示されます。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Lv.{level} のカスタム設定を削除しました。",
            ephemeral=True,
        )

    @chill_config_group.command(
        name="list",
        description="レベルごとのチル場所一覧を表示",
    )
    async def chill_place_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        try:
            async with async_session() as session:
                places = await chill_service.list_chill_places(
                    session,
                    str(interaction.guild_id),
                )
        except Exception:
            logger.exception(
                "Failed to list guild chill places guild=%s",
                interaction.guild_id,
            )
            await interaction.response.send_message(
                "一覧の取得に失敗しました。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            truncate(format_chill_list(places)),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChillCommandsCog(bot))
