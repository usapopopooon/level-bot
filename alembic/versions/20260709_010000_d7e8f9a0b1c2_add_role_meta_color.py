"""add color to role_meta

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-07-09 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "role_meta",
        sa.Column("color", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("role_meta", "color", server_default=None)


def downgrade() -> None:
    op.drop_column("role_meta", "color")
