#!/usr/bin/env python3
"""Backfill chill-place data from intro-bot Postgres into level-bot Postgres.

The script is idempotent: destination rows are upserted by the same natural keys
used by both bots.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class GuildChillPlaceRow:
    guild_id: str
    required_level: int
    name: str
    emoji: str | None


@dataclass(frozen=True)
class UserChillPlaceRow:
    guild_id: str
    user_id: str
    required_level: int


def _normalize_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill chill-place rows from intro-bot DB to level-bot DB."
    )
    parser.add_argument(
        "--intro-database-url",
        default=os.environ.get("INTRO_DATABASE_URL", ""),
        help="intro-bot DATABASE_URL. Defaults to INTRO_DATABASE_URL.",
    )
    parser.add_argument(
        "--level-database-url",
        default=os.environ.get("LEVEL_DATABASE_URL")
        or os.environ.get("DATABASE_URL", ""),
        help="level-bot DATABASE_URL. Defaults to LEVEL_DATABASE_URL or DATABASE_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and report counts without writing to level-bot DB.",
    )
    return parser.parse_args()


async def _fetch_intro_rows(
    intro_url: str,
) -> tuple[list[GuildChillPlaceRow], list[UserChillPlaceRow]]:
    conn = await asyncpg.connect(_normalize_asyncpg_url(intro_url))
    try:
        guild_rows = await conn.fetch(
            """
            SELECT guild_id::text AS guild_id, required_level, name, emoji
            FROM guild_chill_places
            ORDER BY guild_id, required_level
            """
        )
        user_rows = await conn.fetch(
            """
            SELECT guild_id::text AS guild_id, user_id::text AS user_id, required_level
            FROM user_chill_places
            ORDER BY guild_id, user_id
            """
        )
        return (
            [
                GuildChillPlaceRow(
                    guild_id=row["guild_id"],
                    required_level=row["required_level"],
                    name=row["name"],
                    emoji=row["emoji"],
                )
                for row in guild_rows
            ],
            [
                UserChillPlaceRow(
                    guild_id=row["guild_id"],
                    user_id=row["user_id"],
                    required_level=row["required_level"],
                )
                for row in user_rows
            ],
        )
    finally:
        await conn.close()


async def _write_level_rows(
    level_url: str,
    guild_rows: list[GuildChillPlaceRow],
    user_rows: list[UserChillPlaceRow],
) -> None:
    conn = await asyncpg.connect(_normalize_asyncpg_url(level_url))
    try:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO guild_chill_places (guild_id, required_level, name, emoji)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, required_level) DO UPDATE
                SET name = EXCLUDED.name,
                    emoji = EXCLUDED.emoji,
                    updated_at = NOW()
                """,
                [
                    (row.guild_id, row.required_level, row.name, row.emoji)
                    for row in guild_rows
                ],
            )
            await conn.executemany(
                """
                INSERT INTO user_chill_places (guild_id, user_id, required_level)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, user_id) DO UPDATE
                SET required_level = EXCLUDED.required_level,
                    updated_at = NOW()
                """,
                [(row.guild_id, row.user_id, row.required_level) for row in user_rows],
            )
    finally:
        await conn.close()


async def _main() -> int:
    args = _parse_args()
    if not args.intro_database_url:
        raise SystemExit("INTRO_DATABASE_URL or --intro-database-url is required")
    if not args.level_database_url:
        raise SystemExit(
            "LEVEL_DATABASE_URL, DATABASE_URL, or --level-database-url is required"
        )

    guild_rows, user_rows = await _fetch_intro_rows(args.intro_database_url)
    print(
        "Read intro chill rows: "
        f"guild_chill_places={len(guild_rows)} user_chill_places={len(user_rows)}"
    )
    if args.dry_run:
        print("Dry run: no rows written.")
        return 0

    await _write_level_rows(args.level_database_url, guild_rows, user_rows)
    print(
        "Backfilled level chill rows: "
        f"guild_chill_places={len(guild_rows)} user_chill_places={len(user_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
