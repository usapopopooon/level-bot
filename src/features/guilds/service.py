"""Guild + GuildSettings + ExcludedChannel CRUD.

Bot 側ライフサイクル (guild_join/remove/update) と Web/スラッシュコマンドの
両方から呼ばれる。Guild は集計の起点なので、ここが落ちると他 feature が
壊れることに注意。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import (
    ExcludedChannel,
    ExcludedUser,
    Guild,
    GuildSettings,
    LevelRoleAward,
    RoleMeta,
)
from src.level_roles import LevelRoleGrantMode, validate_level_role_grant_mode

# =============================================================================
# Guild + Settings
# =============================================================================


async def upsert_guild(
    session: AsyncSession,
    *,
    guild_id: str,
    name: str,
    icon_url: str | None,
    member_count: int,
) -> Guild:
    """Guild レコードを upsert する。Bot 起動時 / guild_join / guild_update で呼ぶ。"""
    stmt = select(Guild).where(Guild.guild_id == guild_id)
    result = await session.execute(stmt)
    guild = result.scalar_one_or_none()

    if guild is None:
        guild = Guild(
            guild_id=guild_id,
            name=name,
            icon_url=icon_url,
            member_count=member_count,
            is_active=True,
        )
        session.add(guild)
        await session.flush()
        # デフォルト設定も作成
        session.add(GuildSettings(guild_pk=guild.id))
    else:
        guild.name = name
        guild.icon_url = icon_url
        guild.member_count = member_count
        guild.is_active = True

    await session.commit()
    return guild


async def mark_guild_inactive(session: AsyncSession, guild_id: str) -> None:
    """Bot が kick された / guild_remove イベント時に呼ぶ。"""
    stmt = select(Guild).where(Guild.guild_id == guild_id)
    result = await session.execute(stmt)
    guild = result.scalar_one_or_none()
    if guild:
        guild.is_active = False
        await session.commit()


async def get_guild_settings(
    session: AsyncSession, guild_id: str
) -> GuildSettings | None:
    """ギルド設定を取得する (Guild の上書きされたデフォルト)。"""
    stmt = (
        select(GuildSettings)
        .join(Guild, GuildSettings.guild_pk == Guild.id)
        .where(Guild.guild_id == guild_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_active_guilds(session: AsyncSession) -> list[Guild]:
    """アクティブなギルド一覧 (Web トップページ用)。

    ``settings`` を eager-load しておかないと、async session で
    relationship アクセス時に MissingGreenlet エラーになる。
    """
    stmt = (
        select(Guild)
        .where(Guild.is_active.is_(True))
        .options(selectinload(Guild.settings))
        .order_by(Guild.name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def request_level_role_sync(session: AsyncSession, guild_id: str) -> bool:
    settings = await get_guild_settings(session, guild_id)
    if settings is None:
        return False
    settings.level_role_sync_requested_at = datetime.now(UTC)
    await session.commit()
    return True


async def list_guild_ids_requiring_level_role_sync(session: AsyncSession) -> list[str]:
    stmt = (
        select(Guild.guild_id)
        .join(GuildSettings, GuildSettings.guild_pk == Guild.id)
        .where(Guild.is_active.is_(True))
        .where(GuildSettings.level_role_sync_requested_at.is_not(None))
        .where(
            or_(
                GuildSettings.level_role_sync_processed_at.is_(None),
                GuildSettings.level_role_sync_requested_at
                > GuildSettings.level_role_sync_processed_at,
            )
        )
        .order_by(Guild.guild_id.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [row[0] for row in rows]


async def mark_level_role_sync_processed(session: AsyncSession, guild_id: str) -> bool:
    settings = await get_guild_settings(session, guild_id)
    if settings is None:
        return False
    settings.level_role_sync_processed_at = datetime.now(UTC)
    await session.commit()
    return True


# =============================================================================
# Excluded channels
# =============================================================================


async def is_channel_excluded(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = select(ExcludedChannel.id).where(
        and_(
            ExcludedChannel.guild_id == guild_id,
            ExcludedChannel.channel_id == channel_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_excluded_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    """除外リストに追加する。既に存在すれば False。"""
    if await is_channel_excluded(session, guild_id, channel_id):
        return False
    session.add(ExcludedChannel(guild_id=guild_id, channel_id=channel_id))
    await session.commit()
    return True


async def remove_excluded_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = delete(ExcludedChannel).where(
        and_(
            ExcludedChannel.guild_id == guild_id,
            ExcludedChannel.channel_id == channel_id,
        )
    )
    # DML の execute は CursorResult を返すが、typed stub では Result[Any] のため明示
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return (result.rowcount or 0) > 0


async def list_excluded_channels(session: AsyncSession, guild_id: str) -> list[str]:
    stmt = select(ExcludedChannel.channel_id).where(
        ExcludedChannel.guild_id == guild_id
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def clear_excluded_channels(session: AsyncSession, guild_id: str) -> int:
    """ギルドの除外チャンネルを全解除し、解除件数を返す。"""
    stmt = delete(ExcludedChannel).where(ExcludedChannel.guild_id == guild_id)
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return result.rowcount or 0


# =============================================================================
# Excluded users (display-side only — daily_stats は書き込み継続)
# =============================================================================


async def is_user_excluded(session: AsyncSession, guild_id: str, user_id: str) -> bool:
    stmt = select(ExcludedUser.id).where(
        and_(
            ExcludedUser.guild_id == guild_id,
            ExcludedUser.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_excluded_user(session: AsyncSession, guild_id: str, user_id: str) -> bool:
    """表示除外リストに追加する。既に存在すれば False。"""
    if await is_user_excluded(session, guild_id, user_id):
        return False
    session.add(ExcludedUser(guild_id=guild_id, user_id=user_id))
    await session.commit()
    return True


async def remove_excluded_user(
    session: AsyncSession, guild_id: str, user_id: str
) -> bool:
    stmt = delete(ExcludedUser).where(
        and_(
            ExcludedUser.guild_id == guild_id,
            ExcludedUser.user_id == user_id,
        )
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return (result.rowcount or 0) > 0


async def list_excluded_users(session: AsyncSession, guild_id: str) -> list[str]:
    stmt = select(ExcludedUser.user_id).where(ExcludedUser.guild_id == guild_id)
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def clear_excluded_users(session: AsyncSession, guild_id: str) -> int:
    """ギルドの除外ユーザーを全解除し、解除件数を返す。"""
    stmt = delete(ExcludedUser).where(ExcludedUser.guild_id == guild_id)
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return result.rowcount or 0


async def get_excluded_user_ids_set(session: AsyncSession, guild_id: str) -> set[str]:
    """``in`` 判定を頻繁に行う読み出し系のため set で返す。"""
    return set(await list_excluded_users(session, guild_id))


@dataclass
class LevelRoleAwardView:
    slot: int
    grant_mode: LevelRoleGrantMode
    level: int
    role_id: str
    role_name: str


LevelRoleAwardByNameRule = tuple[int, str, int, str]
LevelRoleAwardByIdRule = tuple[int, str, int, str]
ResolvedLevelRoleAwardRule = tuple[int, str, int, LevelRoleGrantMode]


def _validate_level_role_rule_shape(
    *,
    seen_slot_levels: set[tuple[int, int]],
    slot_modes: dict[int, LevelRoleGrantMode],
    level: int,
    slot: int,
    grant_mode: str,
) -> tuple[bool, LevelRoleGrantMode | str]:
    key = (slot, level)
    if key in seen_slot_levels:
        return False, f"Duplicate rule in slot={slot} level={level}"
    seen_slot_levels.add(key)

    try:
        validated_mode = validate_level_role_grant_mode(grant_mode)
    except ValueError as exc:
        return False, str(exc)

    previous_mode = slot_modes.setdefault(slot, validated_mode)
    if previous_mode != validated_mode:
        return False, f"Mixed grant_mode in slot={slot}"
    return True, validated_mode


async def list_level_role_awards(
    session: AsyncSession, guild_id: str
) -> list[LevelRoleAwardView]:
    stmt = (
        select(
            LevelRoleAward.slot,
            LevelRoleAward.grant_mode,
            LevelRoleAward.level,
            LevelRoleAward.role_id,
            RoleMeta.name,
        )
        .outerjoin(
            RoleMeta,
            and_(
                RoleMeta.guild_id == LevelRoleAward.guild_id,
                RoleMeta.role_id == LevelRoleAward.role_id,
            ),
        )
        .where(LevelRoleAward.guild_id == guild_id)
        .order_by(LevelRoleAward.slot.asc(), LevelRoleAward.level.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        LevelRoleAwardView(
            slot=row[0],
            grant_mode=validate_level_role_grant_mode(row[1]),
            level=row[2],
            role_id=row[3],
            role_name=row[4] or row[3],
        )
        for row in rows
    ]


async def _resolve_role_id_by_name(
    session: AsyncSession, guild_id: str, role_name: str
) -> str | None:
    stmt = select(RoleMeta.role_id).where(
        and_(RoleMeta.guild_id == guild_id, RoleMeta.name == role_name)
    )
    role_ids = (await session.execute(stmt)).scalars().all()
    if len(role_ids) != 1:
        return None
    return role_ids[0]


async def replace_level_role_awards_by_name(
    session: AsyncSession, guild_id: str, rules: Sequence[LevelRoleAwardByNameRule]
) -> tuple[bool, str | None]:
    """(level, role_name, slot, grant_mode) の全置換。

    role_name は guild 内で一意である必要がある。
    """
    resolved: list[ResolvedLevelRoleAwardRule] = []
    seen_slot_levels: set[tuple[int, int]] = set()
    slot_modes: dict[int, LevelRoleGrantMode] = {}
    for level, role_name, slot, grant_mode in rules:
        ok, mode_or_err = _validate_level_role_rule_shape(
            seen_slot_levels=seen_slot_levels,
            slot_modes=slot_modes,
            level=level,
            slot=slot,
            grant_mode=grant_mode,
        )
        if not ok:
            return False, str(mode_or_err)
        validated_mode = cast(LevelRoleGrantMode, mode_or_err)
        role_id = await _resolve_role_id_by_name(session, guild_id, role_name)
        if role_id is None:
            return (
                False,
                f"Role name '{role_name}' not found or ambiguous in this guild",
            )
        resolved.append((level, role_id, slot, validated_mode))

    await session.execute(
        delete(LevelRoleAward).where(LevelRoleAward.guild_id == guild_id)
    )
    for level, role_id, slot, grant_mode in resolved:
        session.add(
            LevelRoleAward(
                guild_id=guild_id,
                slot=slot,
                grant_mode=grant_mode,
                level=level,
                role_id=role_id,
            )
        )
    await session.commit()
    return True, None


async def replace_level_role_awards_by_id(
    session: AsyncSession, guild_id: str, rules: Sequence[LevelRoleAwardByIdRule]
) -> tuple[bool, str | None]:
    """(level, role_id, slot, grant_mode) の全置換。

    role_id が guild 内に存在することを検証する。
    """
    seen_slot_levels: set[tuple[int, int]] = set()
    slot_modes: dict[int, LevelRoleGrantMode] = {}
    validated: list[ResolvedLevelRoleAwardRule] = []
    for level, role_id, slot, grant_mode in rules:
        ok, mode_or_err = _validate_level_role_rule_shape(
            seen_slot_levels=seen_slot_levels,
            slot_modes=slot_modes,
            level=level,
            slot=slot,
            grant_mode=grant_mode,
        )
        if not ok:
            return False, str(mode_or_err)
        validated_mode = cast(LevelRoleGrantMode, mode_or_err)
        exists_stmt = select(RoleMeta.id).where(
            and_(RoleMeta.guild_id == guild_id, RoleMeta.role_id == role_id)
        )
        exists = (await session.execute(exists_stmt)).scalar_one_or_none()
        if exists is None:
            return False, f"Role id '{role_id}' not found in this guild"
        validated.append((level, role_id, slot, validated_mode))

    await session.execute(
        delete(LevelRoleAward).where(LevelRoleAward.guild_id == guild_id)
    )
    for level, role_id, slot, grant_mode in validated:
        session.add(
            LevelRoleAward(
                guild_id=guild_id,
                slot=slot,
                grant_mode=grant_mode,
                level=level,
                role_id=role_id,
            )
        )
    await session.commit()
    return True, None


async def list_level_role_awards_for_grant(
    session: AsyncSession, guild_id: str
) -> list[LevelRoleAward]:
    stmt = (
        select(LevelRoleAward)
        .where(LevelRoleAward.guild_id == guild_id)
        .order_by(LevelRoleAward.slot.asc(), LevelRoleAward.level.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
