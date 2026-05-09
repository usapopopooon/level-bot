"""Public read-only API routes for guild listings."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.guilds import service as gs
from src.features.guilds.schemas import GuildOut
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["guilds"])


@router.get("/guilds", response_model=list[GuildOut])
async def list_guilds(db: AsyncSession = Depends(get_db)) -> list[GuildOut]:
    """公開設定のあるアクティブギルドの一覧を返す。"""
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
