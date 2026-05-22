"""add XP weight rollback target

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-05-22 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "level_xp_weight_change_logs",
        sa.Column("target_effective_from", sa.Date(), nullable=True),
    )
    op.create_index(
        op.f("ix_level_xp_weight_change_logs_target_effective_from"),
        "level_xp_weight_change_logs",
        ["target_effective_from"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_level_xp_weight_change_logs_target_effective_from"),
        table_name="level_xp_weight_change_logs",
    )
    op.drop_column("level_xp_weight_change_logs", "target_effective_from")
