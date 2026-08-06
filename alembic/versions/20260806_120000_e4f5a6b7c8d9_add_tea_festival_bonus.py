"""add tea festival bonus seconds

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column(
            "tea_festival_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "voice_party_states",
        sa.Column(
            "tier",
            sa.String(),
            nullable=False,
            server_default="inactive",
        ),
    )
    op.add_column(
        "voice_party_states",
        sa.Column("announced_tier", sa.String(), nullable=True),
    )
    # この機能より前は、人数にかかわらず全てティーパーティーだった。
    op.execute(
        "UPDATE voice_party_states "
        "SET tier = 'tea_party' "
        "WHERE active = true"
    )
    op.execute(
        "UPDATE voice_party_states "
        "SET announced_tier = 'tea_party' "
        "WHERE announced = true"
    )


def downgrade() -> None:
    op.drop_column("voice_party_states", "announced_tier")
    op.drop_column("voice_party_states", "tier")
    op.drop_column("daily_stats", "tea_festival_seconds")
