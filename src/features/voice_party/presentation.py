"""ティーパーティーボーナスのDiscord Embed。"""

from __future__ import annotations

import discord

from src.constants import DEFAULT_EMBED_COLOR
from src.features.voice_party.service import (
    TEA_CARNIVAL_MULTIPLIER,
    TEA_FESTIVAL_MULTIPLIER,
    VOICE_CAFE_TALK_MULTIPLIER,
    VOICE_PARTY_MULTIPLIER,
)


def cafe_talk_started_embed() -> discord.Embed:
    return discord.Embed(
        title="☕ カフェトークボーナス！",
        description=(
            "二人席の時間が、ゆっくり馴染んできました。\n"
            "ここまでの時間を含め、VC XPが "
            f"**{VOICE_CAFE_TALK_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )


def cafe_talk_current_embed() -> discord.Embed:
    return discord.Embed(
        title="☕ カフェトークボーナス中",
        description=(
            "二人席の穏やかな時間が続いています。\n"
            "VC XPは "
            f"**{VOICE_CAFE_TALK_MULTIPLIER:g}倍** です。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )


def cafe_talk_ended_embed() -> discord.Embed:
    return discord.Embed(
        title="☕ カフェトークボーナス終了",
        description="二人席の時間が終わり、VC XPは通常に戻りました。",
        color=DEFAULT_EMBED_COLOR,
    )


def voice_party_started_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="☕ ティーパーティーボーナス開始！",
        description=(
            "このVCに3人以上集まりました！\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{VOICE_PARTY_MULTIPLIER:g}倍** になります。"
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
            f"**{VOICE_PARTY_MULTIPLIER:g}倍** になります。"
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


def tea_festival_started_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="🫖 ティーフェスティバルボーナス開始！",
        description=(
            "このVCに5人以上集まりました！\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{TEA_FESTIVAL_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(
        text="4人以下でティーパーティー、10人以上でティーカーニバルに移行します"
    )
    return embed


def tea_festival_current_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="🫖 ティーフェスティバルボーナス開催中！",
        description=(
            "このVCでは現在5人以上が参加しているため、"
            "ティーフェスティバルボーナスが適用されています。\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{TEA_FESTIVAL_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(
        text="4人以下でティーパーティー、10人以上でティーカーニバルに移行します"
    )
    return embed


def tea_festival_ended_embed() -> discord.Embed:
    return discord.Embed(
        title="🫖 ティーフェスティバルボーナス終了",
        description=(
            "このVCの参加者が2人以下になったため、"
            "VCで獲得するサーバーXPは通常に戻りました。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )


def tea_carnival_started_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="🎪 ティーカーニバルボーナス開始！",
        description=(
            "このVCに10人以上集まりました！\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{TEA_CARNIVAL_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(text="9人以下になるとティーフェスティバルに移行します")
    return embed


def tea_carnival_current_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="🎪 ティーカーニバルボーナス開催中！",
        description=(
            "このVCでは現在10人以上が参加しているため、"
            "ティーカーニバルボーナスが適用されています。\n"
            "参加中は、VCで獲得するサーバーXPが "
            f"**{TEA_CARNIVAL_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(text="9人以下になるとティーフェスティバルに移行します")
    return embed


def tea_carnival_ended_embed() -> discord.Embed:
    return discord.Embed(
        title="🎪 ティーカーニバルボーナス終了",
        description=(
            "このVCの参加者が2人以下になったため、"
            "VCで獲得するサーバーXPは通常に戻りました。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )


def tea_festival_downgraded_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="🫖 ティーフェスティバルボーナスに移行しました",
        description=(
            "このVCの参加人数が9人以下になったため、"
            "VCで獲得するサーバーXPは "
            f"**{TEA_FESTIVAL_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(
        text="4人以下でティーパーティー、10人以上でティーカーニバルに移行します"
    )
    return embed


def voice_party_downgraded_embed(member_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="☕ ティーパーティーボーナスに移行しました",
        description=(
            "このVCの参加人数が4人以下になったため、"
            "VCで獲得するサーバーXPは "
            f"**{VOICE_PARTY_MULTIPLIER:g}倍** になります。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.add_field(name="現在の参加人数", value=f"{member_count}人")
    embed.set_footer(text="同じVCの人数が2人以下になると終了します")
    return embed
