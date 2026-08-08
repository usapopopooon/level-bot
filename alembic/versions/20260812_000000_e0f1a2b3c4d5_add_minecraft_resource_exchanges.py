"""add Minecraft resource exchange ledger

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-08-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_resource_exchanges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cost_xp > 0", name="ck_minecraft_resource_exchanges_cost"),
        sa.CheckConstraint(
            "item_count > 0", name="ck_minecraft_resource_exchanges_count"
        ),
        sa.CheckConstraint(
            "item_id IN ('minecraft:diamond', 'minecraft:emerald')",
            name="ck_minecraft_resource_exchanges_item",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'completed', 'cancelled')",
            name="ck_minecraft_resource_exchanges_status",
        ),
        sa.UniqueConstraint(
            "event_id", name="uq_minecraft_resource_exchanges_event_id"
        ),
    )
    op.create_index(
        "ix_minecraft_resource_exchanges_guild_id",
        "minecraft_resource_exchanges",
        ["guild_id"],
    )
    op.create_index(
        "ix_minecraft_resource_exchanges_user_id",
        "minecraft_resource_exchanges",
        ["user_id"],
    )
    op.create_index(
        "ix_minecraft_resource_exchanges_status",
        "minecraft_resource_exchanges",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("minecraft_resource_exchanges")
