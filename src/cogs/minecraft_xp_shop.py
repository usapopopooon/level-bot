"""Minecraft XP交換所の公開パネルと本人限定UI。"""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.color_role_shop.service import wallet_for_user
from src.features.leveling.service import get_user_lifetime_levels
from src.features.minecraft_xp_shop import service as shop_service


async def _total_xp_for_user(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> int:
    levels = await get_user_lifetime_levels(session, guild_id, user_id)
    if levels is None:
        return 0
    return (
        levels.voice.xp
        + levels.text.xp
        + levels.reactions_received.xp
        + levels.reactions_given.xp
        + levels.minecraft.xp
    )


def build_minecraft_xp_shop_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Minecraft XP交換所",
        description=(
            "活動で貯めたサーバーXPをMinecraft内のXPポイントへ交換できます。\n"
            "連携したMinecraftアカウントでサーバーに参加中のみ交換できます。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(
        name="交換内容",
        value="\n".join(
            f"`サーバーXP {pack.cost_xp:,}` → `Minecraft {pack.reward_xp:,} XP`"
            for pack in shop_service.MINECRAFT_XP_PACKS
        ),
        inline=False,
    )
    embed.set_footer(text="交換操作と残高は本人にだけ表示されます")
    return embed


class MinecraftXpPackSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, guild_id: str, user_id: int) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        super().__init__(
            placeholder="交換するXPを選択",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=(
                        f"サーバーXP {pack.cost_xp:,} → Minecraft {pack.reward_xp:,} XP"
                    ),
                    value=str(pack.cost_xp),
                )
                for pack in shop_service.MINECRAFT_XP_PACKS
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この交換メニューを使えるのは開いた本人だけです。", ephemeral=True
            )
            return
        cost_xp = int(self.values[0])
        pack = shop_service.find_pack(cost_xp)
        if pack is None:
            await interaction.response.send_message(
                "この交換内容は利用できません。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            total_xp = await _total_xp_for_user(
                session, guild_id=self.guild_id, user_id=str(self.user_id)
            )
            wallet = await wallet_for_user(
                session,
                guild_id=self.guild_id,
                user_id=str(self.user_id),
                total_xp=total_xp,
            )
        affordable = wallet.available_xp >= pack.cost_xp
        embed = discord.Embed(
            title="交換内容の確認",
            description=(
                f"サーバーXP **{pack.cost_xp:,}** を使い、Minecraft内の "
                f"**{pack.reward_xp:,} XP**を獲得します。\n"
                f"現在の交換可能XP: **{wallet.available_xp:,} XP**"
            ),
            color=DEFAULT_EMBED_COLOR,
        )
        embed.add_field(
            name="交換後",
            value=(
                f"{wallet.available_xp - pack.cost_xp:,} XP"
                if affordable
                else "XPが不足しています"
            ),
        )
        await interaction.followup.send(
            embed=embed,
            view=MinecraftXpConfirmView(
                guild_id=self.guild_id,
                user_id=self.user_id,
                cost_xp=pack.cost_xp,
                affordable=affordable,
            ),
            ephemeral=True,
        )


class MinecraftXpPackSelectView(discord.ui.View):
    def __init__(self, guild_id: str, user_id: int) -> None:
        super().__init__(timeout=180)
        self.add_item(MinecraftXpPackSelect(guild_id, user_id))


class MinecraftXpConfirmView(discord.ui.View):
    def __init__(
        self, *, guild_id: str, user_id: int, cost_xp: int, affordable: bool
    ) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user_id = user_id
        self.cost_xp = cost_xp
        if not affordable:
            self.confirm.disabled = True

    @discord.ui.button(label="交換する", style=discord.ButtonStyle.primary)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この交換を確定できるのは本人だけです。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            total_xp = await _total_xp_for_user(
                session, guild_id=self.guild_id, user_id=str(self.user_id)
            )
            result = await shop_service.request_exchange(
                session,
                guild_id=self.guild_id,
                user_id=str(self.user_id),
                cost_xp=self.cost_xp,
                total_xp=total_xp,
            )
        await interaction.followup.send(result.message, ephemeral=True)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この交換をキャンセルできるのは本人だけです。", ephemeral=True
            )
            return
        await interaction.response.edit_message(content="交換をキャンセルしました。")


class DynamicMinecraftXpShopButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:minecraft-xp:open:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="XPを交換",
                style=discord.ButtonStyle.primary,
                custom_id=f"level:minecraft-xp:open:{guild_id}",
                emoji="⛏️",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicMinecraftXpShopButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で利用してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(self.guild_id)
        async with async_session() as session:
            total_xp = await _total_xp_for_user(
                session, guild_id=guild_id, user_id=str(interaction.user.id)
            )
            wallet = await wallet_for_user(
                session,
                guild_id=guild_id,
                user_id=str(interaction.user.id),
                total_xp=total_xp,
            )
        await interaction.followup.send(
            (
                f"交換可能XP: **{wallet.available_xp:,} XP**\n"
                "交換内容を選んでください。Minecraftサーバーへの参加中のみ交換できます。"
            ),
            view=MinecraftXpPackSelectView(guild_id, interaction.user.id),
            ephemeral=True,
        )


class MinecraftXpShopPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicMinecraftXpShopButton(guild_id))


class MinecraftXpShopCog(commands.Cog):
    minecraft_xp_group = app_commands.Group(
        name="minecraft-xp",
        description="Minecraft XP交換所の管理",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @minecraft_xp_group.command(name="panel", description="Minecraft XP交換所を投稿")
    async def post_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=build_minecraft_xp_shop_embed(),
            view=MinecraftXpShopPanelView(interaction.guild.id),
        )


def register_minecraft_xp_shop_dynamic_items(bot: commands.Bot) -> None:
    bot.add_dynamic_items(DynamicMinecraftXpShopButton)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MinecraftXpShopCog(bot))
