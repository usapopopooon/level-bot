"""禅タイムのDiscord Embed。"""

from __future__ import annotations

import discord

from src.constants import DEFAULT_EMBED_COLOR


def voice_zen_reward_embed(*, user_id: str, minutes: int, xp: int) -> discord.Embed:
    if minutes == 10:
        title = "🧘 禅タイム開始！"
        description = (
            f"<@{user_id}>さんがVCで10分間、静かなひとときを過ごしました。\n"
            f"禅タイムに入り、**{xp} XP**を獲得しました！"
        )
    else:
        duration = f"{minutes // 60}時間" if minutes % 60 == 0 else f"{minutes}分"
        title = f"🧘 禅タイム{duration}達成！"
        description = (
            f"<@{user_id}>さんがVCで{duration}の禅タイムを達成し、"
            f"**{xp} XP**を獲得しました！"
        )
    embed = discord.Embed(
        title=title,
        description=description,
        color=DEFAULT_EMBED_COLOR,
    )
    embed.set_footer(text="1人で過ごした時間が続くと、さらに禅タイム報酬を獲得できます")
    return embed


def voice_zen_ended_embed(
    *, user_id: str, participant_count: int, user_still_present: bool = False
) -> discord.Embed:
    if participant_count >= 2:
        description = (
            f"<@{user_id}>さんの静かなひとときに仲間が加わりました。"
            "禅タイムを終了します。"
        )
    elif user_still_present:
        description = (
            f"<@{user_id}>さんがミュート状態になったため、禅タイムを終了しました。"
        )
    else:
        description = f"<@{user_id}>さんがVCから退出したため、禅タイムを終了しました。"
    return discord.Embed(
        title="🍵 禅タイム終了",
        description=description,
        color=DEFAULT_EMBED_COLOR,
    )
