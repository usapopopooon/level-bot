"""add Minecraft item gacha XP spends

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_item_gacha_spends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("draw_day", sa.Date(), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cost_xp = 100", name="ck_minecraft_item_gacha_spends_cost"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled')",
            name="ck_minecraft_item_gacha_spends_status",
        ),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint(
            "guild_id",
            "user_id",
            "draw_day",
            name="uq_minecraft_item_gacha_spends_user_day",
        ),
    )
    for column in ("draw_day", "guild_id", "status", "user_id"):
        op.create_index(
            f"ix_minecraft_item_gacha_spends_{column}",
            "minecraft_item_gacha_spends",
            [column],
        )


def downgrade() -> None:
    op.drop_table("minecraft_item_gacha_spends")
