"""add cafe medals and cosmetic unlocks

Revision ID: 6d1a2f9c8b30
Revises: e7c4a9b2d6f1
Create Date: 2026-08-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6d1a2f9c8b30"
down_revision: str | Sequence[str] | None = "e7c4a9b2d6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cafe_gacha_medal_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reward_medals", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reward_medals >= 1", name="ck_cafe_medal_reward"),
    )
    for column in ("guild_id", "user_id"):
        op.create_index(
            f"ix_cafe_gacha_medal_redemptions_{column}",
            "cafe_gacha_medal_redemptions",
            [column],
        )
    op.create_table(
        "cafe_gacha_medal_redemption_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "redemption_id",
            sa.Integer(),
            sa.ForeignKey("cafe_gacha_medal_redemptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reward_key", sa.String(length=64), nullable=False),
        sa.Column("rarity", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("medals_per_card", sa.Integer(), nullable=False),
        sa.Column("reward_medals", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity >= 1", name="ck_cafe_medal_item_quantity"),
        sa.CheckConstraint("medals_per_card >= 1", name="ck_cafe_medal_item_rate"),
        sa.CheckConstraint("reward_medals >= 1", name="ck_cafe_medal_item_reward"),
    )
    op.create_index(
        "ix_cafe_gacha_medal_redemption_items_redemption_id",
        "cafe_gacha_medal_redemption_items",
        ["redemption_id"],
    )
    op.create_index(
        "ix_cafe_gacha_medal_redemption_items_reward_key",
        "cafe_gacha_medal_redemption_items",
        ["reward_key"],
    )
    op.create_table(
        "cafe_gacha_cosmetic_unlocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("cosmetic_key", sa.String(length=64), nullable=False),
        sa.Column("cost_medals", sa.Integer(), nullable=False),
        sa.Column("equipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "guild_id", "user_id", "cosmetic_key", name="uq_cafe_cosmetic_unlock"
        ),
        sa.CheckConstraint("cost_medals >= 0", name="ck_cafe_cosmetic_cost"),
    )
    for column in ("guild_id", "user_id"):
        op.create_index(
            f"ix_cafe_gacha_cosmetic_unlocks_{column}",
            "cafe_gacha_cosmetic_unlocks",
            [column],
        )


def downgrade() -> None:
    op.drop_table("cafe_gacha_cosmetic_unlocks")
    op.drop_table("cafe_gacha_medal_redemption_items")
    op.drop_table("cafe_gacha_medal_redemptions")
