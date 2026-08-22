"""カフェ・コレクションのセットメニューUI。"""

from __future__ import annotations

import discord

from src.cogs.feature_access import ensure_feature_access
from src.constants import DEFAULT_EMBED_COLOR
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.sets import SETS, completed_set_keys
from src.features.feature_access import service as feature_access_service

SET_MENU_PAGE_SIZE = 10


def _set_menu_embed(lifetime_owned_keys: set[str], page: int) -> discord.Embed:
    page_count = max(1, (len(SETS) + SET_MENU_PAGE_SIZE - 1) // SET_MENU_PAGE_SIZE)
    if not 0 <= page < page_count:
        msg = f"page must be between 0 and {page_count - 1}"
        raise ValueError(msg)

    completed = completed_set_keys(lifetime_owned_keys)
    embed = discord.Embed(
        title="🍽️ セットメニュー帳",
        description=(
            f"完成 **{len(completed)}/{len(SETS)}セット**\n"
            "一度でも引いたカードで判定するため、重複交換後も達成は消えません。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    start = page * SET_MENU_PAGE_SIZE
    for item in SETS[start : start + SET_MENU_PAGE_SIZE]:
        missing = [
            CARDS_BY_KEY[key].name
            for key in item.required_keys
            if key not in lifetime_owned_keys
        ]
        embed.add_field(
            name=f"{'✅' if not missing else '⬜'} {item.name}",
            value=(
                f"{item.description}\n"
                + ("完成済み" if not missing else f"あと: {'、'.join(missing)}")
            ),
            inline=False,
        )
    embed.set_footer(text=f"ページ {page + 1}/{page_count}")
    return embed


class CafeSetMenuView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        lifetime_owned_keys: set[str],
        page: int,
    ) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.lifetime_owned_keys = lifetime_owned_keys
        self.page = page
        page_count = max(1, (len(SETS) + SET_MENU_PAGE_SIZE - 1) // SET_MENU_PAGE_SIZE)
        self.previous.disabled = page == 0
        self.next.disabled = page == page_count - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return False
        return await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        )

    async def _show_page(self, interaction: discord.Interaction, page: int) -> None:
        await interaction.response.edit_message(
            embed=_set_menu_embed(self.lifetime_owned_keys, page),
            view=CafeSetMenuView(
                self.guild_id,
                self.user_id,
                self.lifetime_owned_keys,
                page,
            ),
        )

    @discord.ui.button(label="前へ", style=discord.ButtonStyle.secondary)
    async def previous(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await self._show_page(interaction, self.page - 1)

    @discord.ui.button(label="次へ", style=discord.ButtonStyle.secondary)
    async def next(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await self._show_page(interaction, self.page + 1)


class CafeSetMenuButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(label="セットメニュー", emoji="🍽️", row=3)
        self.guild_id = guild_id
        self.user_id = user_id
        self.lifetime_owned_keys = {
            item.card.key for item in collection if item.lifetime_count > 0
        }

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.send_message(
            embed=_set_menu_embed(self.lifetime_owned_keys, 0),
            view=CafeSetMenuView(
                self.guild_id,
                self.user_id,
                self.lifetime_owned_keys,
                0,
            ),
            ephemeral=True,
        )
