"""add XP gift panel configuration and transfer ledger

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "xp_gift_guild_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("panel_channel_id", sa.String(), nullable=False),
        sa.Column("ledger_channel_id", sa.String(), nullable=False),
        sa.Column("panel_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id"),
    )
    op.create_index(
        op.f("ix_xp_gift_guild_configs_guild_id"),
        "xp_gift_guild_configs",
        ["guild_id"],
        unique=True,
    )
    op.create_table(
        "xp_gift_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("sender_user_id", sa.String(), nullable=False),
        sa.Column("sender_display_name", sa.String(length=80), nullable=False),
        sa.Column("recipient_user_id", sa.String(), nullable=False),
        sa.Column("recipient_display_name", sa.String(length=80), nullable=False),
        sa.Column("gift_xp", sa.Integer(), nullable=False),
        sa.Column("tax_xp", sa.Integer(), nullable=False),
        sa.Column("sender_cost_xp", sa.Integer(), nullable=False),
        sa.Column("transfer_day", sa.Date(), nullable=False),
        sa.Column("ledger_message_id", sa.String(), nullable=True),
        sa.Column(
            "notification_attempts", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sender_user_id <> recipient_user_id",
            name="ck_xp_gift_distinct_users",
        ),
        sa.CheckConstraint(
            "gift_xp BETWEEN 1 AND 3000", name="ck_xp_gift_amount"
        ),
        sa.CheckConstraint("tax_xp >= 0", name="ck_xp_gift_tax"),
        sa.CheckConstraint(
            "sender_cost_xp = gift_xp + tax_xp",
            name="ck_xp_gift_sender_cost",
        ),
        sa.CheckConstraint(
            "notification_attempts BETWEEN 0 AND 5",
            name="ck_xp_gift_notification_attempts",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint(
            "guild_id",
            "sender_user_id",
            "recipient_user_id",
            "transfer_day",
            name="uq_xp_gift_sender_recipient_day",
        ),
    )
    for column in (
        "created_at",
        "guild_id",
        "recipient_user_id",
        "sender_user_id",
        "transfer_day",
    ):
        op.create_index(
            op.f(f"ix_xp_gift_transfers_{column}"),
            "xp_gift_transfers",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("xp_gift_transfers")
    op.drop_table("xp_gift_guild_configs")
