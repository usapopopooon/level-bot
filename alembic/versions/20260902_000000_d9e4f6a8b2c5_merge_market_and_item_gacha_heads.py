"""merge Minecraft market and item gacha migration heads

Revision ID: d9e4f6a8b2c5
Revises: b7c2e4f6a819, a5e7c9f1b3d6
Create Date: 2026-09-02 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "d9e4f6a8b2c5"
down_revision: str | Sequence[str] | None = (
    "b7c2e4f6a819",
    "a5e7c9f1b3d6",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
