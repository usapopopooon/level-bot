"""Ports for level-bot data that is not owned by Cafe Collection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class ExternalCardConsumptionPort(Protocol):
    """Read card consumption recorded by integrations outside Cafe Collection."""

    async def consumed_card_counts(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> Mapping[str, int]: ...


class LeaderboardAudiencePort(Protocol):
    """Resolve users that must not appear in public Cafe rankings."""

    async def blocked_user_ids(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> set[str]: ...


class PublicGuildAccessPort(Protocol):
    """Decide whether Cafe data for a guild may be exposed publicly."""

    async def is_public_guild(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> bool: ...


class UserPresentationPort(Protocol):
    """Resolve optional presentation data owned by the host bot."""

    async def avatar_urls(
        self,
        session: AsyncSession,
        *,
        user_ids: tuple[str, ...],
    ) -> Mapping[str, str | None]: ...


@dataclass(frozen=True)
class CafeGachaDependencies:
    external_consumption: ExternalCardConsumptionPort
    leaderboard_audience: LeaderboardAudiencePort
    public_guild_access: PublicGuildAccessPort
    user_presentation: UserPresentationPort
