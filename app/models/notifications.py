"""Private notifications and optional durable email delivery."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class NotificationPreference(TimestampMixin, Base):
    """Per-account/category channel choices; email requires separate verified-address opt-in."""
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(24), primary_key=True)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Private record-reference notice and durable optional-email claim/retry state."""
    __tablename__ = "notifications"

    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(32))
    event_key: Mapped[str] = mapped_column(String(160))
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE")
    )
    reply_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_replies.id", ondelete="CASCADE")
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_connections.id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("direct_messages.id", ondelete="CASCADE")
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    learning_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="SET NULL"), index=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mentorship_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mentorship_requests.id", ondelete="CASCADE"), index=True
    )
    application_status: Mapped[str] = mapped_column(String(24), default="")
    email_to: Mapped[str] = mapped_column(String(254), default="")
    email_state: Mapped[str] = mapped_column(String(16), default="skipped")
    email_attempts: Mapped[int] = mapped_column(Integer, default=0)
    email_next_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_lease_token: Mapped[str | None] = mapped_column(String(32))

    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id])
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])

    __table_args__ = (
        UniqueConstraint("recipient_id", "event_key", name="uq_notification_event_recipient"),
        Index("notification_inbox_idx", "recipient_id", "in_app", "created_at", "id"),
        Index("notification_unread_idx", "recipient_id", "read_at"),
        Index("notification_delivery_idx", "email_state", "email_next_attempt"),
    )
