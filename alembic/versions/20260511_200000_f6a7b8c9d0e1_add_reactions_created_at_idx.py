"""add reactions.created_at index for retention purge

``purge_old_reactions`` の WHERE created_at < cutoff を index 駆動にするため、
``reactions.created_at`` にインデックスを足す。

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-11 20:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_reactions_created_at", "reactions", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_reactions_created_at", table_name="reactions")
