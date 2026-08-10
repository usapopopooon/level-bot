"""rename K-Brot cafe card

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-19 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET reward_name = 'Kブロート',
            reward_description = 'ジャガイモでかさ増しされた、戦時下の代用パン。'
        WHERE reward_key = 'k-pan'
        """
    )
    op.execute(
        """
        UPDATE cafe_gacha_redemption_items
        SET reward_name = 'Kブロート'
        WHERE reward_key = 'k-pan'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET reward_name = 'Kパン',
            reward_description = '固さも歴史も折り紙つきの保存パン。'
        WHERE reward_key = 'k-pan'
        """
    )
    op.execute(
        """
        UPDATE cafe_gacha_redemption_items
        SET reward_name = 'Kパン'
        WHERE reward_key = 'k-pan'
        """
    )
