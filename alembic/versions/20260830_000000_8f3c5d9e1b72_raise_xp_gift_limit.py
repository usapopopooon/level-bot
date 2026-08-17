"""raise XP gift limit

Revision ID: 8f3c5d9e1b72
Revises: 7e2b4c8d0a91
Create Date: 2026-08-30 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8f3c5d9e1b72"
down_revision: str | Sequence[str] | None = "7e2b4c8d0a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_xp_gift_amount",
        "xp_gift_transfers",
        type_="check",
    )
    op.create_check_constraint(
        "ck_xp_gift_amount",
        "xp_gift_transfers",
        "gift_xp BETWEEN 1 AND 5000",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM xp_gift_transfers WHERE gift_xp > 3000
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade XP gift limit while transfers above 3000 exist';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        "ck_xp_gift_amount",
        "xp_gift_transfers",
        type_="check",
    )
    op.create_check_constraint(
        "ck_xp_gift_amount",
        "xp_gift_transfers",
        "gift_xp BETWEEN 1 AND 3000",
    )
