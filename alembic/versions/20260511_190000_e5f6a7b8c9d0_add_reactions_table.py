"""add reactions table

(誰が / 誰の / どのメッセージに / どの絵文字を) を個別に記録する表。
レベル算出時の「1 メッセージ × 1 リアクター = 1 カウント」の重複検出に使う。

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-11 19:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, index=True),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False, index=True),
        sa.Column("reactor_id", sa.String(), nullable=False, index=True),
        sa.Column(
            "message_author_id", sa.String(), nullable=False, index=True
        ),
        sa.Column("emoji", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "message_id", "reactor_id", "emoji", name="uq_reaction"
        ),
    )
    # (message_id, reactor_id) 単位での件数取得用 covering index。
    # ホットパスの「このリアクターがこのメッセージにいくつ絵文字を付けているか」
    # の count(*) を index-only で済ませる。
    op.create_index(
        "ix_reactions_message_reactor",
        "reactions",
        ["message_id", "reactor_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reactions_message_reactor", table_name="reactions")
    op.drop_table("reactions")
