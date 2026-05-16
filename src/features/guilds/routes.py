"""Public read-only API routes for guild listings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.guilds import service as gs
from src.features.guilds.schemas import (
    GuildOut,
    GuildRoleOut,
    LevelRoleAwardOut,
    LevelRoleAwardsUpdateIn,
)
from src.features.meta import service as meta_service
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["guilds"])


@router.get(
    "/guilds",
    response_model=list[GuildOut],
    summary="ギルド一覧",
    description=(
        "Bot が参加していて、かつ公開設定 (`guild_settings.public=true`) の"
        "ギルドを返す。非公開ギルドは応答に含まれない。"
    ),
)
async def list_guilds(db: AsyncSession = Depends(get_db)) -> list[GuildOut]:
    guilds = await gs.list_active_guilds(db)
    return [
        GuildOut(
            guild_id=g.guild_id,
            name=g.name,
            icon_url=g.icon_url,
            member_count=g.member_count,
        )
        for g in guilds
        if (g.settings is None or g.settings.public)
    ]


@router.get(
    "/guilds/{guild_id}/roles",
    response_model=list[GuildRoleOut],
    summary="ギルドのロール候補",
)
async def list_roles(
    guild_id: str, db: AsyncSession = Depends(get_db)
) -> list[GuildRoleOut]:
    rows = await meta_service.list_roles_in_guild(db, guild_id)
    return [
        GuildRoleOut(
            role_id=r.role_id,
            role_name=r.name,
            position=r.position,
            is_managed=r.is_managed,
        )
        for r in rows
        if not r.is_managed and r.name != "@everyone"
    ]


@router.get(
    "/guilds/{guild_id}/level-role-awards",
    response_model=list[LevelRoleAwardOut],
    summary="レベル到達ロール付与設定",
)
async def get_level_role_awards(
    guild_id: str, db: AsyncSession = Depends(get_db)
) -> list[LevelRoleAwardOut]:
    rows = await gs.list_level_role_awards(db, guild_id)
    return [
        LevelRoleAwardOut(
            slot=r.slot, level=r.level, role_id=r.role_id, role_name=r.role_name
        )
        for r in rows
    ]


@router.put(
    "/guilds/{guild_id}/level-role-awards",
    response_model=list[LevelRoleAwardOut],
    summary="レベル到達ロール付与設定を更新",
)
async def put_level_role_awards(
    guild_id: str,
    payload: LevelRoleAwardsUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> list[LevelRoleAwardOut]:
    normalized = []
    for item in payload.rules:
        if item.slot <= 0:
            raise HTTPException(status_code=422, detail="slot must be >= 1")
        if item.level < 0:
            raise HTTPException(status_code=422, detail="level must be >= 0")
        role_id = item.role_id.strip()
        if not role_id.isdigit():
            raise HTTPException(status_code=422, detail="role_id must be digit string")
        normalized.append((item.level, role_id, item.slot))

    ok, err = await gs.replace_level_role_awards_by_id(db, guild_id, normalized)
    if not ok:
        raise HTTPException(status_code=422, detail=err or "Invalid rules")
    await gs.request_level_role_sync(db, guild_id)

    rows = await gs.list_level_role_awards(db, guild_id)
    return [
        LevelRoleAwardOut(
            slot=r.slot, level=r.level, role_id=r.role_id, role_name=r.role_name
        )
        for r in rows
    ]
