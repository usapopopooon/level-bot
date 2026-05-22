"""add XP weight change logs

Revision ID: a9b0c1d2e3f4
Revises: f2a3b4c5d6e7
Create Date: 2026-05-22 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "level_xp_weight_change_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_id", sa.String(length=64), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("previous_message_weight", sa.Float(), nullable=True),
        sa.Column("previous_reaction_received_weight", sa.Float(), nullable=True),
        sa.Column("previous_reaction_given_weight", sa.Float(), nullable=True),
        sa.Column("new_message_weight", sa.Float(), nullable=False),
        sa.Column("new_reaction_received_weight", sa.Float(), nullable=False),
        sa.Column("new_reaction_given_weight", sa.Float(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "change_id",
            name="uq_level_xp_weight_change_logs_change_id",
        ),
    )
    op.create_index(
        op.f("ix_level_xp_weight_change_logs_created_at"),
        "level_xp_weight_change_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_level_xp_weight_change_logs_effective_from"),
        "level_xp_weight_change_logs",
        ["effective_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_level_xp_weight_change_logs_guild_id"),
        "level_xp_weight_change_logs",
        ["guild_id"],
        unique=False,
    )

    # 既存の全体共通レートを、監査ログ導入時点の初期変更ログとして保存する。
    op.execute(
        """
        INSERT INTO level_xp_weight_change_logs (
            change_id,
            guild_id,
            effective_from,
            operation,
            previous_message_weight,
            previous_reaction_received_weight,
            previous_reaction_given_weight,
            new_message_weight,
            new_reaction_received_weight,
            new_reaction_given_weight,
            actor_id,
            reason,
            created_at
        )
        SELECT
            'seed-' || id::text,
            NULL,
            effective_from,
            'seed',
            NULL,
            NULL,
            NULL,
            message_weight,
            reaction_received_weight,
            reaction_given_weight,
            NULL,
            'Initial audit log seed from level_xp_weight_logs',
            created_at
        FROM level_xp_weight_logs
        ORDER BY effective_from ASC
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_level_xp_weight_change_logs_guild_id"),
        table_name="level_xp_weight_change_logs",
    )
    op.drop_index(
        op.f("ix_level_xp_weight_change_logs_effective_from"),
        table_name="level_xp_weight_change_logs",
    )
    op.drop_index(
        op.f("ix_level_xp_weight_change_logs_created_at"),
        table_name="level_xp_weight_change_logs",
    )
    op.drop_table("level_xp_weight_change_logs")
