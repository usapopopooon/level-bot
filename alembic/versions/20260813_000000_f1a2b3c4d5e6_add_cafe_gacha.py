"""add cafe gacha collection and ledgers

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-08-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cafe_gacha_guild_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, unique=True),
        sa.Column("counter_channel_id", sa.String(), nullable=False),
        sa.Column("ledger_channel_id", sa.String(), nullable=False),
        sa.Column("panel_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_cafe_gacha_guild_configs_guild_id",
        "cafe_gacha_guild_configs",
        ["guild_id"],
        unique=True,
    )
    op.create_table(
        "cafe_gacha_user_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("last_free_draw_on", sa.Date(), nullable=True),
        sa.Column("favorite_reward_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_cafe_gacha_user_state"),
    )
    op.create_index(
        "ix_cafe_gacha_user_states_guild_id",
        "cafe_gacha_user_states",
        ["guild_id"],
    )
    op.create_index(
        "ix_cafe_gacha_user_states_user_id",
        "cafe_gacha_user_states",
        ["user_id"],
    )
    op.create_table(
        "cafe_gacha_draws",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("draw_type", sa.String(length=16), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("reward_key", sa.String(length=64), nullable=False),
        sa.Column("reward_name", sa.String(length=80), nullable=False),
        sa.Column("reward_description", sa.String(length=240), nullable=False),
        sa.Column("rarity", sa.String(length=4), nullable=False),
        sa.Column("image_filename", sa.String(length=100), nullable=False),
        sa.Column("exchange_xp", sa.Integer(), nullable=False),
        sa.Column("was_duplicate", sa.Boolean(), nullable=False),
        sa.Column("owned_count", sa.Integer(), nullable=False),
        sa.Column("collected_count", sa.Integer(), nullable=False),
        sa.Column("counter_message_id", sa.String(), nullable=True),
        sa.Column("counter_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ledger_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "draw_type IN ('free', 'paid')", name="ck_cafe_gacha_draw_type"
        ),
        sa.CheckConstraint(
            "rarity IN ('C', 'UC', 'R', 'SR', 'SSR')",
            name="ck_cafe_gacha_draw_rarity",
        ),
        sa.CheckConstraint("cost_xp >= 0", name="ck_cafe_gacha_draw_cost"),
        sa.CheckConstraint("owned_count >= 1", name="ck_cafe_gacha_draw_owned_count"),
        sa.CheckConstraint(
            "collected_count >= 1", name="ck_cafe_gacha_draw_collected_count"
        ),
    )
    for column in ("guild_id", "user_id", "reward_key", "created_at"):
        op.create_index(f"ix_cafe_gacha_draws_{column}", "cafe_gacha_draws", [column])
    op.create_table(
        "cafe_gacha_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("reward_xp", sa.Integer(), nullable=False),
        sa.Column("counter_message_id", sa.String(), nullable=True),
        sa.Column("ledger_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reward_xp >= 1", name="ck_cafe_gacha_redemption_reward"),
    )
    for column in ("guild_id", "user_id", "created_at"):
        op.create_index(
            f"ix_cafe_gacha_redemptions_{column}",
            "cafe_gacha_redemptions",
            [column],
        )
    op.create_table(
        "cafe_gacha_redemption_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "redemption_id",
            sa.Integer(),
            sa.ForeignKey("cafe_gacha_redemptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reward_key", sa.String(length=64), nullable=False),
        sa.Column("reward_name", sa.String(length=80), nullable=False),
        sa.Column("rarity", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("xp_per_card", sa.Integer(), nullable=False),
        sa.Column("reward_xp", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "quantity >= 1", name="ck_cafe_gacha_redemption_item_quantity"
        ),
        sa.CheckConstraint(
            "xp_per_card >= 1", name="ck_cafe_gacha_redemption_item_rate"
        ),
        sa.CheckConstraint(
            "reward_xp >= 1", name="ck_cafe_gacha_redemption_item_reward"
        ),
    )
    op.create_index(
        "ix_cafe_gacha_redemption_items_redemption_id",
        "cafe_gacha_redemption_items",
        ["redemption_id"],
    )
    op.create_index(
        "ix_cafe_gacha_redemption_items_reward_key",
        "cafe_gacha_redemption_items",
        ["reward_key"],
    )


def downgrade() -> None:
    op.drop_table("cafe_gacha_redemption_items")
    op.drop_table("cafe_gacha_redemptions")
    op.drop_table("cafe_gacha_draws")
    op.drop_table("cafe_gacha_user_states")
    op.drop_table("cafe_gacha_guild_configs")
