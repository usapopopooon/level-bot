"""add grant_mode to level_role_awards

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-18 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "level_role_awards",
        sa.Column(
            "grant_mode",
            sa.String(length=16),
            nullable=False,
            server_default="replace",
        ),
    )
    op.create_check_constraint(
        "ck_level_role_awards_grant_mode",
        "level_role_awards",
        "grant_mode IN ('replace', 'stack')",
    )
    op.alter_column("level_role_awards", "grant_mode", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_level_role_awards_grant_mode",
        "level_role_awards",
        type_="check",
    )
    op.drop_column("level_role_awards", "grant_mode")
