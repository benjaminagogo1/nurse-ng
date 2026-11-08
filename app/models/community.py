"""Public community conversations, relationships, reports, and moderation."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class ContentStatus(StrEnum):
    PROCESSING = "processing"
    PUBLISHED = "published"
    REMOVED = "removed"


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    REEL_SOURCE = "reel_source"
    REEL_LOW = "reel_low"
    REEL_POSTER = "reel_poster"


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReportReason(StrEnum):
    SPAM = "spam"
    HARASSMENT = "harassment"
    MISINFORMATION = "misinformation"
    PRIVACY = "privacy"
    OTHER = "other"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class CommunityTopic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_topics"

    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    posts: Mapped[list["CommunityPost"]] = relationship(back_populates="topic")


class CommunityPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_posts"

    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_topics.id", ondelete="RESTRICT"), index=True
    )
    body: Mapped[str] = mapped_column(Text, default="")
    external_video_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=ContentStatus.PUBLISHED, index=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    removed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removal_reason: Mapped[str] = mapped_column(Text, default="")

    author: Mapped[User] = relationship(foreign_keys=[author_id])
    topic: Mapped[CommunityTopic] = relationship(back_populates="posts")
    media: Mapped[list["CommunityMedia"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="CommunityMedia.position",
    )
    replies: Mapped[list["CommunityReply"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="CommunityReply.created_at",
    )

    __table_args__ = (
        Index("community_post_topic_status_idx", "topic_id", "status"),
    )


class CommunityMedia(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_media"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    storage_name: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    post: Mapped[CommunityPost] = relationship(back_populates="media")


class CommunityReply(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_replies"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_replies.id", ondelete="SET NULL", name="fk_community_reply_parent"),
        nullable=True, index=True,
    )
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default=ContentStatus.PUBLISHED, index=True
    )
    removed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removal_reason: Mapped[str] = mapped_column(Text, default="")

    post: Mapped[CommunityPost] = relationship(back_populates="replies")
    author: Mapped[User] = relationship(foreign_keys=[author_id])

    __table_args__ = (
        Index("community_reply_activity_idx", "post_id", "status", "created_at"),
        CheckConstraint("in_reply_to_id IS NULL OR in_reply_to_id != id",
                        name="community_reply_not_self"),
    )


class DiscussionFollow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A private subscription to a public conversation, independent of people follows."""

    __tablename__ = "discussion_follows"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), index=True
    )
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uniq_discussion_follow"),
    )


class DiscussionReplyRead(Base):
    """Private record of a reply rendered for one discussion follower."""

    __tablename__ = "discussion_reply_reads"

    follow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discussion_follows.id", ondelete="CASCADE"), primary_key=True
    )
    reply_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_replies.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class ContentReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_reports"

    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    reply_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_replies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(30))
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(20), default=ReportStatus.OPEN, index=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str] = mapped_column(Text, default="")
    # Present only while open. A unique key closes the race between two
    # duplicate report submissions from the same member (DECISIONS L69).
    open_key: Mapped[str | None] = mapped_column(String(80), nullable=True)

    post: Mapped[CommunityPost | None] = relationship(foreign_keys=[post_id])
    reply: Mapped[CommunityReply | None] = relationship(foreign_keys=[reply_id])

    __table_args__ = (
        CheckConstraint(
            "(post_id IS NOT NULL AND reply_id IS NULL) OR "
            "(post_id IS NULL AND reply_id IS NOT NULL)",
            name="content_report_one_target",
        ),
        UniqueConstraint("open_key", name="uniq_content_report_open_key"),
    )


class Follow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_follows"

    follower_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    followed_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "follower_user_id",
            "followed_user_id",
            name="uniq_community_follow",
        ),
        CheckConstraint(
            "follower_user_id != followed_user_id",
            name="community_follow_not_self",
        ),
    )


class Connection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_connections"

    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=ConnectionStatus.PENDING, index=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Canonical unordered user pair. Requester/recipient still record direction.
    pair_key: Mapped[str] = mapped_column(String(65))

    __table_args__ = (
        UniqueConstraint(
            "requester_user_id",
            "recipient_user_id",
            name="uniq_community_connection_direction",
        ),
        UniqueConstraint("pair_key", name="uniq_community_connection_pair"),
        CheckConstraint(
            "requester_user_id != recipient_user_id",
            name="community_connection_not_self",
        ),
    )
