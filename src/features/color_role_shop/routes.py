"""Color-role shop management API routes."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.features.color_role_shop import presentation as color_role_presentation
from src.features.color_role_shop import service as color_role_service
from src.features.color_role_shop.schemas import (
    ColorRoleShopItemOut,
    ColorRoleShopItemUpsertIn,
    ColorRoleShopPanelPostIn,
    ColorRoleShopPanelPostOut,
)
from src.features.guilds import service as guilds_service
from src.features.meta import service as meta_service
from src.web.deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["color-role-shop"])

_DISCORD_API_BASE_URL = "https://discord.com/api/v10"


def _item_out(item: color_role_service.ColorRoleItemView) -> ColorRoleShopItemOut:
    return ColorRoleShopItemOut(
        id=item.id,
        role_id=item.role_id,
        role_name=item.label,
        label=item.label,
        description=item.description,
        cost_xp=item.cost_xp,
    )


async def _post_discord_message(
    channel_id: str,
    payload: dict[str, Any],
) -> str:
    """Discord REST で channel に message を新規投稿し、message_id を返す。"""
    token = settings.discord_token.strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="DISCORD_TOKEN is required to post a color-role panel",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_DISCORD_API_BASE_URL}/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail="Bot cannot send messages to the selected channel",
        )
    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="Selected channel was not found or is not accessible",
        )
    if response.status_code >= 400:
        logger.warning(
            "Discord panel post failed channel=%s status=%s body=%s",
            channel_id,
            response.status_code,
            response.text[:500],
        )
        raise HTTPException(status_code=502, detail="Discord panel post failed")

    body = response.json()
    message_id = str(body.get("id") or "")
    if not message_id:
        raise HTTPException(
            status_code=502,
            detail="Discord response missed message id",
        )
    return message_id


@router.get(
    "/guilds/{guild_id}/color-role-shop/items",
    response_model=list[ColorRoleShopItemOut],
    summary="カラーロール交換対象一覧",
)
async def list_color_role_items(
    guild_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ColorRoleShopItemOut]:
    items = await color_role_service.list_enabled_color_role_items(db, guild_id)
    return [_item_out(item) for item in items]


@router.put(
    "/guilds/{guild_id}/color-role-shop/items/{role_id}",
    response_model=ColorRoleShopItemOut,
    summary="カラーロール交換対象を追加または更新",
)
async def put_color_role_item(
    guild_id: str,
    role_id: str,
    payload: ColorRoleShopItemUpsertIn,
    db: AsyncSession = Depends(get_db),
) -> ColorRoleShopItemOut:
    if payload.role_id != role_id:
        raise HTTPException(status_code=422, detail="role_id path/body mismatch")
    if payload.cost_xp < color_role_service.MIN_COLOR_ROLE_COST_XP:
        raise HTTPException(status_code=422, detail="cost_xp must be >= 1")

    role = await meta_service.get_role_meta(db, guild_id=guild_id, role_id=role_id)
    if role is None:
        raise HTTPException(status_code=422, detail="Unknown role_id")
    if role.is_managed or role.name == "@everyone":
        raise HTTPException(status_code=422, detail="Role is not exchangeable")

    item = await color_role_service.upsert_color_role_item(
        db,
        guild_id=guild_id,
        role_id=role_id,
        label=role.name,
        cost_xp=payload.cost_xp,
        description=payload.description,
    )
    return _item_out(item)


@router.delete(
    "/guilds/{guild_id}/color-role-shop/items/{role_id}",
    status_code=204,
    summary="カラーロール交換対象を無効化",
)
async def delete_color_role_item(
    guild_id: str,
    role_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await color_role_service.disable_color_role_item(
        db,
        guild_id=guild_id,
        role_id=role_id,
    )
    return Response(status_code=204)


@router.post(
    "/guilds/{guild_id}/color-role-shop/panel",
    response_model=ColorRoleShopPanelPostOut,
    summary="カラーロール交換所パネルを新規投稿",
)
async def post_color_role_panel(
    guild_id: str,
    payload: ColorRoleShopPanelPostIn,
    db: AsyncSession = Depends(get_db),
) -> ColorRoleShopPanelPostOut:
    channel = next(
        (
            candidate
            for candidate in await meta_service.list_channels_in_guild(db, guild_id)
            if candidate.channel_id == payload.channel_id
            and candidate.channel_type == "TextChannel"
        ),
        None,
    )
    if channel is None:
        raise HTTPException(status_code=422, detail="Unknown text channel_id")

    guild = await guilds_service.get_active_guild(db, guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail="Guild not found")

    items = await color_role_service.list_enabled_color_role_items(db, guild_id)
    message_payload = color_role_presentation.build_color_role_panel_message_payload(
        guild_id=guild_id,
        guild_icon_url=guild.icon_url,
        items=items,
    )
    message_id = await _post_discord_message(payload.channel_id, message_payload)
    return ColorRoleShopPanelPostOut(
        channel_id=payload.channel_id,
        message_id=message_id,
    )
