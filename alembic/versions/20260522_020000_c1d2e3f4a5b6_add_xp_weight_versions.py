"""add XP weight versions

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-05-22 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "level_xp_weight_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("message_weight", sa.Float(), nullable=False),
        sa.Column("reaction_received_weight", sa.Float(), nullable=False),
        sa.Column("reaction_given_weight", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("change_log_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'reverted')",
            name="ck_level_xp_weight_versions_status",
        ),
        sa.ForeignKeyConstraint(
            ["change_log_id"],
            ["level_xp_weight_change_logs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["level_xp_weight_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "effective_from",
            "revision",
            name="uq_level_xp_weight_versions_scope_effective_revision",
        ),
    )
    op.create_index(
        op.f("ix_level_xp_weight_versions_change_log_id"),
        "level_xp_weight_versions",
        ["change_log_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_level_xp_weight_versions_created_at"),
        "level_xp_weight_versions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_level_xp_weight_versions_effective_from"),
        "level_xp_weight_versions",
        ["effective_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_level_xp_weight_versions_guild_id"),
        "level_xp_weight_versions",
        ["guild_id"],
        unique=False,
    )

    # 既存の全体共通レートを revision=1 の active version として同期する。
    op.execute(
        """
        INSERT INTO level_xp_weight_versions (
            guild_id,
            effective_from,
            revision,
            message_weight,
            reaction_received_weight,
            reaction_given_weight,
            status,
            created_by,
            created_at,
            supersedes_id,
            change_log_id
        )
        SELECT
            NULL,
            logs.effective_from,
            1,
            logs.message_weight,
            logs.reaction_received_weight,
            logs.reaction_given_weight,
            'active',
            NULL,
            logs.created_at,
            NULL,
            changes.id
        FROM level_xp_weight_logs AS logs
        LEFT JOIN level_xp_weight_change_logs AS changes
          ON changes.change_id = 'seed-' || logs.id::text
        ORDER BY logs.effective_from ASC
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_level_xp_weight_versions_guild_id"),
        table_name="level_xp_weight_versions",
    )
    op.drop_index(
        op.f("ix_level_xp_weight_versions_effective_from"),
        table_name="level_xp_weight_versions",
    )
    op.drop_index(
        op.f("ix_level_xp_weight_versions_created_at"),
        table_name="level_xp_weight_versions",
    )
    op.drop_index(
        op.f("ix_level_xp_weight_versions_change_log_id"),
        table_name="level_xp_weight_versions",
    )
    op.drop_table("level_xp_weight_versions")
