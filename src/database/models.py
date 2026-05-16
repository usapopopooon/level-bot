"""SQLAlchemy database models for level-bot.

テーブル構成:
    - guilds: 統計を取っているサーバー (Discord Guild) のメタ情報
    - guild_settings: サーバー単位の設定 (トラッキング ON/OFF など)
    - excluded_channels: 集計対象から除外するチャンネル
    - daily_stats: ユーザー × チャンネル × 日 単位の集計 (メッセージ・ボイス)
    - voice_sessions: 現在進行中のボイスセッション (退室時に daily_stats へ集計)

すべての Discord ID は安全のため文字列で保持する (snowflake が int64 範囲外になる
ことは無いが、JSON シリアライズや将来的な拡張のため文字列扱いとする慣習に従う)。
"""

from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    validates,
)


def _validate_discord_id(value: str, field_name: str) -> str:
    """Discord ID (数字文字列) のバリデーション。"""
    if not isinstance(value, str) or not value.isdigit():
        msg = f"{field_name} must be a digit string, got: {value!r}"
        raise ValueError(msg)
    return value


class Base(DeclarativeBase):
    """全モデルの基底。Alembic と engine の両方が参照する。"""

    pass


class Guild(Base):
    """統計対象の Discord サーバー (Guild)。

    Bot が join したタイミングで作成し、guild_update / guild_remove で更新する。
    """

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    icon_url: Mapped[str | None] = mapped_column(String, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    settings: Mapped["GuildSettings | None"] = relationship(
        "GuildSettings",
        back_populates="guild",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")


class GuildSettings(Base):
    """ギルド単位の集計設定。"""

    __tablename__ = "guild_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_pk: Mapped[int] = mapped_column(
        ForeignKey("guilds.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # 集計を有効にするか
    tracking_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # Bot のメッセージ・ボイスをカウントするか
    count_bots: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ダッシュボードで公開するか
    public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    guild: Mapped[Guild] = relationship("Guild", back_populates="settings")


class ExcludedChannel(Base):
    """集計対象から除外するチャンネル。

    ``/stats exclude <channel>`` で追加され、その後の集計でスキップされる。
    """

    __tablename__ = "excluded_channels"
    __table_args__ = (
        UniqueConstraint("guild_id", "channel_id", name="uq_excluded_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("channel_id")
    def _v_channel_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "channel_id")


class ExcludedUser(Base):
    """表示から除外するユーザー。

    集計データ自体 (``daily_stats``) は引き続き書き込まれるが、リーダーボード /
    プロフィール / レベル系の **表示** からは除外される。データを残すのは
    後から復帰した時のため (再追加すればすぐ全期間のレベルが復元される)。
    """

    __tablename__ = "excluded_users"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", name="uq_excluded_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("user_id")
    def _v_user_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "user_id")


class DailyStat(Base):
    """ユーザー × チャンネル × 日 単位の集計レコード。

    集計の中核となるテーブル。メッセージ送信・ボイス時間などの増分は
    ``ON CONFLICT DO UPDATE`` (upsert) で1行に集約される。
    """

    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "user_id",
            "channel_id",
            "stat_date",
            name="uq_daily_stat",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # メッセージ系
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # リアクション系
    # reactions_received: このユーザーのメッセージに付いたリアクション数 (人気度)
    # reactions_given:    このユーザーが他人のメッセージに付けたリアクション数 (能動性)
    reactions_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactions_given: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ボイス系 (秒)
    voice_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("user_id")
    def _v_user_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "user_id")

    @validates("channel_id")
    def _v_channel_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "channel_id")


class Reaction(Base):
    """個別リアクションの記録 (誰が誰のメッセージにどの絵文字を付けたか)。

    レベル算出は **1 メッセージ × 1 リアクター = 1 加算** とするため、
    同一 (message, reactor) の組について複数絵文字が付いても daily_stats の
    ``reactions_received`` / ``reactions_given`` への加算は 1 回だけにする
    (このテーブルで重複検出する)。

    監査・「誰から / 誰へ」逆引きにも使える。
    """

    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "reactor_id", "emoji", name="uq_reaction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reactor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_author_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    emoji: Mapped[str] = mapped_column(String, nullable=False)
    # 古い行を ``purge_old_reactions`` で消すための index 付きカラム
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("channel_id")
    def _v_channel_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "channel_id")

    @validates("message_id")
    def _v_message_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "message_id")

    @validates("reactor_id")
    def _v_reactor_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "reactor_id")

    @validates("message_author_id")
    def _v_message_author_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "message_author_id")


class VoiceSession(Base):
    """進行中のボイスセッション。退室イベント時に daily_stats に集計される。

    Bot が再起動した場合に備え、ユニーク制約は (guild_id, user_id) ではなく
    member ごと1セッションが原則 (Discord の仕様上、同時に複数 VC には居られない)。
    """

    __tablename__ = "voice_sessions"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_active_voice_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    self_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    self_deafened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("user_id")
    def _v_user_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "user_id")

    @validates("channel_id")
    def _v_channel_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "channel_id")


class UserMeta(Base):
    """ユーザーメタ情報のキャッシュ。

    Discord API を都度叩かずに名前・アバターを表示できるよう、
    最近の集計対象ユーザーをここにキャッシュする。
    """

    __tablename__ = "user_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("user_id")
    def _v_user_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "user_id")


class ChannelMeta(Base):
    """チャンネルメタ情報のキャッシュ (名前表示用)。"""

    __tablename__ = "channel_meta"
    __table_args__ = (
        UniqueConstraint("guild_id", "channel_id", name="uq_channel_meta"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    channel_type: Mapped[str] = mapped_column(String, nullable=False, default="text")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("channel_id")
    def _v_channel_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "channel_id")


class RoleMeta(Base):
    """ロールメタ情報のキャッシュ (管理画面での表示名サジェスト用)。"""

    __tablename__ = "role_meta"
    __table_args__ = (UniqueConstraint("guild_id", "role_id", name="uq_role_meta"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("role_id")
    def _v_role_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "role_id")


class LevelRoleAward(Base):
    """レベル到達時に付与するロール設定。"""

    __tablename__ = "level_role_awards"
    __table_args__ = (
        UniqueConstraint("guild_id", "level", name="uq_level_role_award_guild_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    role_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @validates("guild_id")
    def _v_guild_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "guild_id")

    @validates("role_id")
    def _v_role_id(self, _key: str, value: str) -> str:
        return _validate_discord_id(value, "role_id")
