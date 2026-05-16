"""add level xp weight logs

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-17 07:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "level_xp_weight_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("message_weight", sa.Float(), nullable=False),
        sa.Column("reaction_received_weight", sa.Float(), nullable=False),
        sa.Column("reaction_given_weight", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "effective_from", name="uq_level_xp_weight_logs_effective_from"
        ),
    )
    op.create_index(
        op.f("ix_level_xp_weight_logs_effective_from"),
        "level_xp_weight_logs",
        ["effective_from"],
        unique=False,
    )

    # 初期実装当時の重み
    op.execute(
        """
        INSERT INTO level_xp_weight_logs
            (effective_from, message_weight, reaction_received_weight, reaction_given_weight, created_at)
        VALUES
            ('1970-01-01', 2.0, 0.5, 0.5, NOW()),
            ('2026-05-17', 30.0, 20.0, 20.0, NOW())
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_level_xp_weight_logs_effective_from"), table_name="level_xp_weight_logs")
    op.drop_table("level_xp_weight_logs")
