"""ティーパーティーボーナスのDiscord Embed。"""

from __future__ import annotations

import discord

from src.constants import DEFAULT_EMBED_COLOR
from src.features.voice_party.service import VOICE_PARTY_MULTIPLIER


def voice_party_started_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="☕ ティーパーティーボーナス開始！",
        description=(
            "このVCに3人以上集まりました！\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{VOICE_PARTY_MULTIPLIER:g}倍** になります。\n"
            "Minecraft同時接続ボーナスとも重なり、その場合は合計 **2.5倍** です。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(text="同じVCの人数が2人以下になると終了します")
    return embed


def voice_party_current_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="☕ ティーパーティーボーナス開催中！",
        description=(
            "このVCでは現在3人以上が参加しているため、"
            "ティーパーティーボーナスが適用されています。\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{VOICE_PARTY_MULTIPLIER:g}倍** になります。\n"
            "Minecraft同時接続ボーナスとも重なり、その場合は合計 **2.5倍** です。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(text="同じVCの人数が2人以下になると終了します")
    return embed


def voice_party_ended_embed() -> discord.Embed:
    return discord.Embed(
        title="☕ ティーパーティーボーナス終了",
        description=(
            "このVCの参加者が2人以下になったため、"
            "VCで獲得するサーバーXPは通常に戻りました。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
