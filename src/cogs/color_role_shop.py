"""カラーロール交換所の Discord UI と管理コマンド。"""

from __future__ import annotations

import logging
import re
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.color_role_shop import presentation as color_role_presentation
from src.features.color_role_shop import service as color_role_service
from src.features.leveling.service import get_user_lifetime_levels
from src.features.meta import service as meta_service

logger = logging.getLogger(__name__)
COLOR_ROLE_OPEN_LABEL = color_role_presentation.COLOR_ROLE_OPEN_LABEL
COLOR_ROLE_BALANCE_LABEL = color_role_presentation.COLOR_ROLE_BALANCE_LABEL
COLOR_ROLE_CLEAR_LABEL = color_role_presentation.COLOR_ROLE_CLEAR_LABEL


async def _total_xp_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> int:
    levels = await get_user_lifetime_levels(
        session,
        guild_id,
        user_id,
    )
    return levels.total.xp if levels is not None else 0


def _role_mention(role_id: str) -> str:
    return color_role_presentation.role_mention(role_id)


def _item_line(item: color_role_service.ColorRoleItemView) -> str:
    return color_role_presentation.item_line(item)


def build_color_role_panel_embed(
    _guild: discord.Guild,
    items: tuple[color_role_service.ColorRoleItemView, ...],
) -> discord.Embed:
    """公開チャンネルに置くカラーロール交換所パネルを作る。"""
    return color_role_presentation.build_color_role_panel_embed(items=items)


def build_color_role_panel_files(
    items: tuple[color_role_service.ColorRoleItemView, ...],
) -> list[discord.File]:
    """公開パネル embed で参照する色見本 PNG を Discord file に変換する。"""
    attachment = color_role_presentation.build_color_role_sample_attachment(items)
    if attachment is None:
        return []
    return [discord.File(BytesIO(attachment.data), filename=attachment.filename)]


async def _send_balance(
    interaction: discord.Interaction,
    guild_id: str,
    user_id: str,
) -> None:
    async with async_session() as session:
        total_xp = await _total_xp_for_user(session, guild_id=guild_id, user_id=user_id)
        wallet = await color_role_service.wallet_for_user(
            session,
            guild_id=guild_id,
            user_id=user_id,
            total_xp=total_xp,
        )
    await interaction.followup.send(
        (
            f"累計XP: **{wallet.total_xp:,} XP**\n"
            f"消費済み: **{wallet.spent_xp:,} XP**\n"
            f"交換可能: **{wallet.available_xp:,} XP**"
        ),
        ephemeral=True,
    )


def _member_from_interaction(interaction: discord.Interaction) -> discord.Member | None:
    if isinstance(interaction.user, discord.Member):
        return interaction.user
    if interaction.guild is None:
        return None
    return interaction.guild.get_member(interaction.user.id)


async def _grant_member_role(
    member: discord.Member,
    role_id: str,
    reason: str,
) -> None:
    role = member.guild.get_role(int(role_id))
    if role is None:
        msg = f"role not found: {role_id}"
        raise RuntimeError(msg)
    await member.add_roles(role, reason=reason)


async def _remove_member_role(
    member: discord.Member,
    role_id: str,
    reason: str,
) -> None:
    role = member.guild.get_role(int(role_id))
    if role is None:
        return
    await member.remove_roles(role, reason=reason)


async def _clear_member_color_roles(
    member: discord.Member,
    *,
    guild_id: str,
) -> tuple[list[str], list[str]]:
    """本人に付いているカラーロールを外し、成功名と失敗 ID を返す。"""
    async with async_session() as session:
        color_role_ids = await color_role_service.list_color_role_ids_for_guild(
            session,
            guild_id,
        )
    member_role_ids = {str(role.id) for role in member.roles}
    removable_role_ids = [
        role_id for role_id in color_role_ids if role_id in member_role_ids
    ]

    removed_names: list[str] = []
    failed_role_ids: list[str] = []
    for role_id in removable_role_ids:
        role = member.guild.get_role(int(role_id))
        if role is None:
            continue
        try:
            await member.remove_roles(role, reason="color role shop clear")
        except Exception:
            logger.exception("Failed to clear color role: %s", role_id)
            failed_role_ids.append(role_id)
        else:
            removed_names.append(role.name)
    return removed_names, failed_role_ids


class ColorRoleSelect(discord.ui.Select[discord.ui.View]):
    """本人だけが使うカラーロール選択。"""

    def __init__(
        self,
        guild_id: str,
        user_id: int,
        items: tuple[color_role_service.ColorRoleItemView, ...],
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        options = [
            discord.SelectOption(
                label=f"{item.label} / {item.cost_xp:,} XP"[:100],
                value=str(item.id),
                description=(item.description or _role_mention(item.role_id))[:100],
            )
            for item in items[: color_role_service.MAX_COLOR_ROLE_SELECT_OPTIONS]
        ]
        super().__init__(
            placeholder="交換したいロールを選択",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この交換メニューを使えるのは開いた本人だけです。",
                ephemeral=True,
            )
            return
        item_id = int(self.values[0])
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            items = await color_role_service.list_enabled_color_role_items(
                session,
                self.guild_id,
                limit=color_role_service.MAX_COLOR_ROLE_SELECT_OPTIONS,
            )
            item = next(
                (candidate for candidate in items if candidate.id == item_id), None
            )
            total_xp = await _total_xp_for_user(
                session,
                guild_id=self.guild_id,
                user_id=str(self.user_id),
            )
            wallet = await color_role_service.wallet_for_user(
                session,
                guild_id=self.guild_id,
                user_id=str(self.user_id),
                total_xp=total_xp,
            )
        if item is None:
            await interaction.followup.send(
                "このロールは現在交換できません。",
                ephemeral=True,
            )
            return
        after = wallet.available_xp - item.cost_xp
        affordable = after >= 0
        embed = discord.Embed(
            title="交換内容の確認",
            description=(
                f"{_role_mention(item.role_id)} を "
                f"**{item.cost_xp:,} XP** で交換します。\n"
                f"現在の交換可能XP: **{wallet.available_xp:,} XP**"
            ),
            color=DEFAULT_EMBED_COLOR,
        )
        if item.description:
            embed.add_field(name="説明", value=item.description, inline=False)
        embed.add_field(
            name="交換後",
            value=f"{max(0, after):,} XP" if affordable else "XP が不足しています",
            inline=True,
        )
        await interaction.followup.send(
            embed=embed,
            view=ColorRoleExchangeConfirmView(
                guild_id=self.guild_id,
                user_id=self.user_id,
                item_id=item.id,
                affordable=affordable,
            ),
            ephemeral=True,
        )


class ColorRoleSelectView(discord.ui.View):
    """カラーロール交換用の本人限定 select view。"""

    def __init__(
        self,
        guild_id: str,
        user_id: int,
        items: tuple[color_role_service.ColorRoleItemView, ...],
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(ColorRoleSelect(guild_id, user_id, items))


class ColorRoleExchangeConfirmView(discord.ui.View):
    """XP 消費前にカラーロール交換の誤操作を防ぐ確認 view。"""

    def __init__(
        self,
        *,
        guild_id: str,
        user_id: int,
        item_id: int,
        affordable: bool,
    ) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user_id = user_id
        self.item_id = item_id
        if not affordable:
            for child in self.children:
                if (
                    isinstance(child, discord.ui.Button)
                    and child.custom_id == "confirm"
                ):
                    child.disabled = True

    @discord.ui.button(
        label="交換する",
        style=discord.ButtonStyle.primary,
        custom_id="confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この交換を確定できるのは本人だけです。",
                ephemeral=True,
            )
            return
        member = _member_from_interaction(interaction)
        if member is None:
            await interaction.response.send_message(
                "サーバーメンバー情報を取得できませんでした。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            selected_items = await color_role_service.list_enabled_color_role_items(
                session, self.guild_id
            )
            selected_item = next(
                (item for item in selected_items if item.id == self.item_id),
                None,
            )
            if selected_item is not None:
                selected_role = member.guild.get_role(int(selected_item.role_id))
                if selected_role is not None and selected_role in member.roles:
                    await interaction.followup.send(
                        "すでにその色が付いています。色を変える場合は別のロールを選んでください。",
                        ephemeral=True,
                    )
                    return
            total_xp = await _total_xp_for_user(
                session,
                guild_id=self.guild_id,
                user_id=str(self.user_id),
            )
            result = await color_role_service.exchange_color_role(
                session,
                guild_id=self.guild_id,
                user_id=str(self.user_id),
                item_id=self.item_id,
                total_xp=total_xp,
                grant_role=lambda role_id, reason: _grant_member_role(
                    member, role_id, reason
                ),
                remove_role=lambda role_id, reason: _remove_member_role(
                    member, role_id, reason
                ),
            )
        await interaction.followup.send(result.message, ephemeral=True)

    @discord.ui.button(
        label="キャンセル",
        style=discord.ButtonStyle.secondary,
        custom_id="cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この交換をキャンセルできるのは本人だけです。",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(content="交換をキャンセルしました。")


class DynamicColorRoleShopOpenButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:color-role:open:(?P<guild_id>\d+)",
):
    """公開パネルから本人限定の交換 select を開くボタン。"""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label=COLOR_ROLE_OPEN_LABEL,
                style=discord.ButtonStyle.primary,
                custom_id=f"level:color-role:open:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicColorRoleShopOpenButton:
        return cls(guild_id=int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で利用してください。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(self.guild_id)
        async with async_session() as session:
            items = await color_role_service.list_enabled_color_role_items(
                session,
                guild_id,
                limit=color_role_service.MAX_COLOR_ROLE_SELECT_OPTIONS,
            )
            total_xp = await _total_xp_for_user(
                session,
                guild_id=guild_id,
                user_id=str(interaction.user.id),
            )
            wallet = await color_role_service.wallet_for_user(
                session,
                guild_id=guild_id,
                user_id=str(interaction.user.id),
                total_xp=total_xp,
            )
        if not items:
            await interaction.followup.send(
                "現在交換できるロールがありません。",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            (
                f"交換可能XP: **{wallet.available_xp:,} XP**\n"
                "交換したい色ロールを選んでください。交換すると他の交換ロールは外れます。"
            ),
            view=ColorRoleSelectView(guild_id, interaction.user.id, items),
            ephemeral=True,
        )


class DynamicColorRoleShopBalanceButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:color-role:balance:(?P<guild_id>\d+)",
):
    """公開パネルから本人の交換可能 XP を表示するボタン。"""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label=COLOR_ROLE_BALANCE_LABEL,
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:color-role:balance:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicColorRoleShopBalanceButton:
        return cls(guild_id=int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _send_balance(interaction, str(self.guild_id), str(interaction.user.id))


class DynamicColorRoleShopClearButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:color-role:clear:(?P<guild_id>\d+)",
):
    """公開パネルから本人のカラーロールを外すボタン。"""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label=COLOR_ROLE_CLEAR_LABEL,
                style=discord.ButtonStyle.danger,
                custom_id=f"level:color-role:clear:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicColorRoleShopClearButton:
        return cls(guild_id=int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で利用してください。",
                ephemeral=True,
            )
            return
        member = _member_from_interaction(interaction)
        if member is None:
            await interaction.response.send_message(
                "サーバーメンバー情報を取得できませんでした。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        removed_names, failed_role_ids = await _clear_member_color_roles(
            member,
            guild_id=str(self.guild_id),
        )
        if failed_role_ids:
            if removed_names:
                await interaction.followup.send(
                    (
                        "一部のカラーロールを外しましたが、外せないロールがありました。"
                        "Bot のロール位置と権限を確認してください。\n"
                        f"外したロール: {', '.join(removed_names)}"
                    ),
                    ephemeral=True,
                )
                return
            await interaction.followup.send(
                (
                    "カラーロールを外せませんでした。"
                    "Bot のロール位置と権限を確認してください。"
                ),
                ephemeral=True,
            )
            return
        if not removed_names:
            await interaction.followup.send(
                "外せるカラーロールは付いていません。",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            (
                f"カラーロールを外しました: {', '.join(removed_names)}\n"
                "XP の払い戻しはありません。"
            ),
            ephemeral=True,
        )


class ColorRoleShopPanelView(discord.ui.View):
    """公開チャンネルに固定するカラーロール交換所パネル view。"""

    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicColorRoleShopOpenButton(guild_id))
        self.add_item(DynamicColorRoleShopBalanceButton(guild_id))
        self.add_item(DynamicColorRoleShopClearButton(guild_id))


class ColorRoleShopCog(commands.Cog):
    """カラーロール交換所の管理コマンド。"""

    color_role_group = app_commands.Group(
        name="color-role",
        description="カラーロール交換所の管理",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @color_role_group.command(
        name="panel", description="カラーロール交換所パネルを投稿"
    )
    async def post_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        guild_id = str(interaction.guild.id)
        async with async_session() as session:
            items = await color_role_service.list_enabled_color_role_items(
                session, guild_id
            )
        await interaction.followup.send(
            embed=build_color_role_panel_embed(interaction.guild, items),
            files=build_color_role_panel_files(items),
            view=ColorRoleShopPanelView(interaction.guild.id),
        )

    @color_role_group.command(
        name="add", description="XPで交換できるカラーロールを追加/更新"
    )
    @app_commands.describe(
        role="交換対象のカラーロール",
        cost_xp="必要XP",
        description="ユーザー向けの短い説明",
    )
    async def add_item(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        cost_xp: int,
        description: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        if role.managed or role.name == "@everyone":
            await interaction.response.send_message(
                "管理ロールや @everyone は交換対象にできません。",
                ephemeral=True,
            )
            return
        if cost_xp < color_role_service.MIN_COLOR_ROLE_COST_XP:
            await interaction.response.send_message(
                "必要XPは 1 以上にしてください。",
                ephemeral=True,
            )
            return
        async with async_session() as session:
            await meta_service.upsert_role_meta(
                session,
                guild_id=str(interaction.guild.id),
                role_id=str(role.id),
                name=role.name,
                position=role.position,
                color=role.color.value,
                is_managed=role.managed,
            )
            item = await color_role_service.upsert_color_role_item(
                session,
                guild_id=str(interaction.guild.id),
                role_id=str(role.id),
                label=role.name,
                cost_xp=cost_xp,
                description=description,
                role_color=role.color.value,
            )
        await interaction.response.send_message(
            f"{role.mention} を {item.cost_xp:,} XP のカラーロール交換対象にしました。",
            ephemeral=True,
        )

    @color_role_group.command(name="remove", description="カラーロール交換対象を無効化")
    @app_commands.describe(role="交換対象から外すカラーロール")
    async def remove_item(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。",
                ephemeral=True,
            )
            return
        async with async_session() as session:
            removed = await color_role_service.disable_color_role_item(
                session,
                guild_id=str(interaction.guild.id),
                role_id=str(role.id),
            )
        if not removed:
            await interaction.response.send_message(
                "そのロールは交換対象に登録されていません。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"{role.mention} をカラーロール交換対象から外しました。",
            ephemeral=True,
        )


def register_color_role_shop_dynamic_items(bot: commands.Bot) -> None:
    """再起動後も公開パネルの DynamicItem を受けられるよう登録する。"""
    bot.add_dynamic_items(
        DynamicColorRoleShopOpenButton,
        DynamicColorRoleShopBalanceButton,
        DynamicColorRoleShopClearButton,
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ColorRoleShopCog(bot))
