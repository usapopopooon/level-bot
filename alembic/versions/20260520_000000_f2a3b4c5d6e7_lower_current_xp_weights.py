"""lower current XP weights

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-20 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO level_xp_weight_logs
            (effective_from, message_weight, reaction_received_weight, reaction_given_weight, created_at)
        VALUES
            ('2026-05-20', 3.0, 2.0, 2.0, NOW())
        ON CONFLICT (effective_from) DO UPDATE SET
            message_weight = EXCLUDED.message_weight,
            reaction_received_weight = EXCLUDED.reaction_received_weight,
            reaction_given_weight = EXCLUDED.reaction_given_weight
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM level_xp_weight_logs
        WHERE effective_from = '2026-05-20'
        """
    )
