"""Temporary persistence boundary for the separately deployed Cafe bot UI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CafeCollectionBotLayout

type CafePlacement = Literal["panel", "ledger", "ranking"]


async def get_layout(
    session: AsyncSession, *, guild_id: str
) -> CafeCollectionBotLayout | None:
    return (
        await session.execute(
            select(CafeCollectionBotLayout).where(
                CafeCollectionBotLayout.guild_id == guild_id
            )
        )
    ).scalar_one_or_none()


async def save_placement(
    session: AsyncSession,
    *,
    guild_id: str,
    placement: CafePlacement,
    channel_id: str,
    message_id: str | None,
) -> CafeCollectionBotLayout:
    """Atomically update one placement without overwriting the other two."""
    await session.execute(
        insert(CafeCollectionBotLayout)
        .values(guild_id=guild_id)
        .on_conflict_do_nothing(index_elements=["guild_id"])
    )
    row = (
        await session.execute(
            select(CafeCollectionBotLayout)
            .where(CafeCollectionBotLayout.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one()
    setattr(row, f"{placement}_channel_id", channel_id)
    setattr(row, f"{placement}_message_id", message_id)
    if placement == "ledger" and row.ledger_configured_at is None:
        row.ledger_configured_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row
