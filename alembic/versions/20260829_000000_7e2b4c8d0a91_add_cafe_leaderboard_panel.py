"""add cafe leaderboard panel message id

Revision ID: 7e2b4c8d0a91
Revises: 6d1a2f9c8b30
Create Date: 2026-08-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7e2b4c8d0a91"
down_revision: str | Sequence[str] | None = "6d1a2f9c8b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cafe_gacha_guild_configs",
        sa.Column("leaderboard_panel_message_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_cafe_gacha_draws_guild_user_reward",
        "cafe_gacha_draws",
        ["guild_id", "user_id", "reward_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cafe_gacha_draws_guild_user_reward",
        table_name="cafe_gacha_draws",
    )
    op.drop_column(
        "cafe_gacha_guild_configs",
        "leaderboard_panel_message_id",
    )
