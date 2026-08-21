"""add minecraft material buybacks

Revision ID: 4f8a2c6e9b31
Revises: a1c2e3f4b5d6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4f8a2c6e9b31"
down_revision: str | Sequence[str] | None = "a1c2e3f4b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_material_buybacks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("item_name", sa.String(length=32), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("reward_xp", sa.Integer(), nullable=False),
        sa.Column("reward_day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("item_count > 0", name="ck_minecraft_buyback_count"),
        sa.CheckConstraint("item_count <= 2304", name="ck_minecraft_buyback_max_count"),
        sa.CheckConstraint(
            "item_count % 64 = 0", name="ck_minecraft_buyback_full_stacks"
        ),
        sa.CheckConstraint("reward_xp > 0", name="ck_minecraft_buyback_reward"),
        sa.CheckConstraint(
            "item_id IN ('minecraft:dirt', 'minecraft:sand', 'minecraft:sandstone', "
            "'minecraft:deepslate', 'minecraft:cobbled_deepslate', "
            "'minecraft:tuff')",
            name="ck_minecraft_buyback_item",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled')",
            name="ck_minecraft_buyback_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        op.f("ix_minecraft_material_buybacks_guild_id"),
        "minecraft_material_buybacks",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_minecraft_material_buybacks_user_id"),
        "minecraft_material_buybacks",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_minecraft_material_buybacks_reward_day"),
        "minecraft_material_buybacks",
        ["reward_day"],
        unique=False,
    )
    op.create_index(
        op.f("ix_minecraft_material_buybacks_status"),
        "minecraft_material_buybacks",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_minecraft_material_buybacks_status"),
        table_name="minecraft_material_buybacks",
    )
    op.drop_index(
        op.f("ix_minecraft_material_buybacks_reward_day"),
        table_name="minecraft_material_buybacks",
    )
    op.drop_index(
        op.f("ix_minecraft_material_buybacks_user_id"),
        table_name="minecraft_material_buybacks",
    )
    op.drop_index(
        op.f("ix_minecraft_material_buybacks_guild_id"),
        table_name="minecraft_material_buybacks",
    )
    op.drop_table("minecraft_material_buybacks")
