"""add voice cafe talk bonus

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column(
            "voice_cafe_talk_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "voice_party_states",
        sa.Column("bonus_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "voice_party_states",
        sa.Column(
            "cafe_talk_pending_seconds_by_date",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("voice_party_states", "cafe_talk_pending_seconds_by_date")
    op.drop_column("voice_party_states", "bonus_started_at")
    op.drop_column("daily_stats", "voice_cafe_talk_seconds")
