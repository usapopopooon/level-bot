from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Guild,
    MinecraftLevelUpEvent,
    MinecraftXpDaily,
    MinecraftXpEvent,
    UserMeta,
)
from src.utils import get_timezone

MINECRAFT_XP_PER_LEVEL_BOT_XP = 100
MINECRAFT_DAILY_AWARD_LIMIT = 100


@dataclass(frozen=True)
class MinecraftXpGrantResult:
    event_id: str
    minecraft_xp: int
    awarded_xp: int
    daily_awarded_xp: int
    duplicate: bool


async def enqueue_minecraft_level_up(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    guild_name: str,
    display_name: str,
    level: int,
) -> bool:
    """レベルアップを冪等にMinecraft通知キューへ追加する。"""
    if level <= 0:
        return False
    result = await session.execute(
        pg_insert(MinecraftLevelUpEvent)
        .values(
            dedupe_key=f"{guild_id}:{user_id}:{level}",
            guild_id=guild_id,
            user_id=user_id,
            guild_name=guild_name[:100],
            display_name=display_name[:100],
            level=level,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=[MinecraftLevelUpEvent.dedupe_key])
        .returning(MinecraftLevelUpEvent.id)
    )
    created = result.scalar_one_or_none() is not None
    await session.commit()
    return created


async def enqueue_minecraft_level_up_from_meta(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    level: int,
) -> bool:
    guild_name = (
        await session.execute(select(Guild.name).where(Guild.guild_id == guild_id))
    ).scalar_one_or_none()
    display_name = (
        await session.execute(
            select(UserMeta.display_name).where(UserMeta.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not guild_name or not display_name:
        return False
    return await enqueue_minecraft_level_up(
        session,
        guild_id=guild_id,
        user_id=user_id,
        guild_name=guild_name,
        display_name=display_name,
        level=level,
    )


async def list_pending_minecraft_level_ups(
    session: AsyncSession, *, guild_id: str, limit: int
) -> list[MinecraftLevelUpEvent]:
    return list(
        (
            await session.execute(
                select(MinecraftLevelUpEvent)
                .where(
                    MinecraftLevelUpEvent.guild_id == guild_id,
                    or_(
                        MinecraftLevelUpEvent.minecraft_delivered_at.is_(None),
                        MinecraftLevelUpEvent.discord_delivered_at.is_(None),
                    ),
                )
                .order_by(MinecraftLevelUpEvent.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def acknowledge_minecraft_level_up(
    session: AsyncSession,
    *,
    guild_id: str,
    event_id: int,
    destination: str,
) -> bool:
    if destination not in {"minecraft", "discord"}:
        raise ValueError("unknown level-up destination")
    delivered_column = (
        MinecraftLevelUpEvent.minecraft_delivered_at
        if destination == "minecraft"
        else MinecraftLevelUpEvent.discord_delivered_at
    )
    result = await session.execute(
        update(MinecraftLevelUpEvent)
        .where(
            MinecraftLevelUpEvent.id == event_id,
            MinecraftLevelUpEvent.guild_id == guild_id,
            delivered_column.is_(None),
        )
        .values({delivered_column.key: datetime.now(UTC)})
        .returning(MinecraftLevelUpEvent.id)
    )
    acknowledged = result.scalar_one_or_none() is not None
    if not acknowledged:
        acknowledged = (
            await session.execute(
                select(MinecraftLevelUpEvent.id).where(
                    MinecraftLevelUpEvent.id == event_id,
                    MinecraftLevelUpEvent.guild_id == guild_id,
                    delivered_column.is_not(None),
                )
            )
        ).scalar_one_or_none() is not None
    await session.commit()
    return acknowledged


async def record_minecraft_xp(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    minecraft_account_id: str,
    minecraft_xp: int,
    observed_at: datetime,
) -> MinecraftXpGrantResult:
    """冪等イベントを記録し、換算残高と日次上限を原子的に適用する。"""
    if minecraft_xp <= 0:
        raise ValueError("minecraft_xp must be positive")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")

    # 同じイベントが同時に再送されても、片方の一意制約違反を500にしない。
    # hash collision は無害（該当トランザクション同士が直列化されるだけ）。
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(event_id, 0)))
    )

    existing = (
        (
            await session.execute(
                select(MinecraftXpEvent).where(MinecraftXpEvent.event_id == event_id)
            )
        )
        .scalars()
        .one_or_none()
    )
    if existing is not None:
        existing_date = existing.observed_at.astimezone(get_timezone()).date()
        existing_daily_award = int(
            (
                await session.execute(
                    select(MinecraftXpDaily.awarded_xp).where(
                        MinecraftXpDaily.guild_id == existing.guild_id,
                        MinecraftXpDaily.user_id == existing.user_id,
                        MinecraftXpDaily.stat_date == existing_date,
                    )
                )
            ).scalar_one()
        )
        await session.commit()
        return MinecraftXpGrantResult(
            event_id=existing.event_id,
            minecraft_xp=existing.minecraft_xp,
            awarded_xp=existing.awarded_xp,
            daily_awarded_xp=existing_daily_award,
            duplicate=True,
        )

    stat_date = observed_at.astimezone(get_timezone()).date()
    await session.execute(
        pg_insert(MinecraftXpDaily)
        .values(
            guild_id=guild_id,
            user_id=user_id,
            stat_date=stat_date,
            minecraft_xp=0,
            awarded_xp=0,
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_minecraft_xp_daily")
    )
    daily = (
        (
            await session.execute(
                select(MinecraftXpDaily)
                .where(
                    MinecraftXpDaily.guild_id == guild_id,
                    MinecraftXpDaily.user_id == user_id,
                    MinecraftXpDaily.stat_date == stat_date,
                )
                .with_for_update()
            )
        )
        .scalars()
        .one()
    )

    new_raw_total = daily.minecraft_xp + minecraft_xp
    target_award = min(
        MINECRAFT_DAILY_AWARD_LIMIT,
        new_raw_total // MINECRAFT_XP_PER_LEVEL_BOT_XP,
    )
    awarded = max(0, target_award - daily.awarded_xp)
    daily.minecraft_xp = new_raw_total
    daily.awarded_xp += awarded
    daily.updated_at = datetime.now(UTC)
    session.add(
        MinecraftXpEvent(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            minecraft_account_id=minecraft_account_id,
            minecraft_xp=minecraft_xp,
            awarded_xp=awarded,
            observed_at=observed_at,
        )
    )
    await session.commit()
    return MinecraftXpGrantResult(
        event_id=event_id,
        minecraft_xp=minecraft_xp,
        awarded_xp=awarded,
        daily_awarded_xp=daily.awarded_xp,
        duplicate=False,
    )
