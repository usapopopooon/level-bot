"""initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-06 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("icon_url", sa.String(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )

    op.create_table(
        "guild_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "guild_pk",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "tracking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "count_bots", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "excluded_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, index=True),
        sa.Column("channel_id", sa.String(), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "channel_id", name="uq_excluded_channel"),
    )

    op.create_table(
        "daily_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, index=True),
        sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("channel_id", sa.String(), nullable=False, index=True),
        sa.Column("stat_date", sa.Date(), nullable=False, index=True),
        sa.Column(
            "message_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "char_count", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "attachment_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "voice_seconds", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "guild_id",
            "user_id",
            "channel_id",
            "stat_date",
            name="uq_daily_stat",
        ),
    )
    # ダッシュボードでの guild_id + stat_date での集計用
    op.create_index(
        "ix_daily_stats_guild_date",
        "daily_stats",
        ["guild_id", "stat_date"],
    )
    op.create_index(
        "ix_daily_stats_guild_user",
        "daily_stats",
        ["guild_id", "user_id"],
    )

    op.create_table(
        "voice_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, index=True),
        sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "self_muted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "self_deafened",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_active_voice_session"),
    )

    op.create_table(
        "user_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("display_name", sa.String(), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "channel_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, index=True),
        sa.Column("channel_id", sa.String(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "channel_type", sa.String(), nullable=False, server_default="text"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "channel_id", name="uq_channel_meta"),
    )


def downgrade() -> None:
    op.drop_table("channel_meta")
    op.drop_table("user_meta")
    op.drop_table("voice_sessions")
    op.drop_index("ix_daily_stats_guild_user", table_name="daily_stats")
    op.drop_index("ix_daily_stats_guild_date", table_name="daily_stats")
    op.drop_table("daily_stats")
    op.drop_table("excluded_channels")
    op.drop_table("guild_settings")
    op.drop_table("guilds")
