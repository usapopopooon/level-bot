"""add independent Minecraft voice bonus cursor

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "minecraft_voice_presences",
        sa.Column("bonus_cursor_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE minecraft_voice_presences "
        "SET bonus_cursor_at = last_seen_at WHERE bonus_cursor_at IS NULL"
    )
    op.alter_column("minecraft_voice_presences", "bonus_cursor_at", nullable=False)


def downgrade() -> None:
    op.drop_column("minecraft_voice_presences", "bonus_cursor_at")
