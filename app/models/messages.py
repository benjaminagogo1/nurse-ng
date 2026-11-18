"""Private messages between accepted network connections."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DirectMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "direct_messages"

    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(String(3000))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="MessageAttachment.position",
    )

    __table_args__ = (
        UniqueConstraint("sender_id", "client_key", name="uq_message_sender_client_key"),
        Index("message_thread_idx", "sender_id", "recipient_id", "created_at", "id"),
    )


class MessageAttachment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "message_attachments"

    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("direct_messages.id", ondelete="CASCADE"),
        index=True,
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    upload_key: Mapped[str] = mapped_column(String(36))
    storage_name: Mapped[str] = mapped_column(String(32), unique=True)
    filename: Mapped[str] = mapped_column(String(180))
    content_type: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[DirectMessage | None] = relationship(back_populates="attachments")

    __table_args__ = (
        UniqueConstraint("sender_id", "upload_key", name="message_attachment_upload_key"),
        UniqueConstraint("message_id", "position", name="message_attachment_position"),
        CheckConstraint("size_bytes > 0", name="message_attachment_size"),
        CheckConstraint(
            "kind IN ('image','audio','video','document')", name="message_attachment_kind"
        ),
        CheckConstraint("sender_id != recipient_id", name="message_attachment_not_self"),
    )


class MessageUploadUsage(Base):
    __tablename__ = "message_upload_usage"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="message_upload_usage_size"),)
