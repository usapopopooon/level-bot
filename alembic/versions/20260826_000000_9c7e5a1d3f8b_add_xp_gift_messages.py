"""add optional messages to XP gifts

Revision ID: 9c7e5a1d3f8b
Revises: f3a4b5c6d7e8
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c7e5a1d3f8b"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "xp_gift_transfers",
        sa.Column("gift_message", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("xp_gift_transfers", "gift_message")
