"""Private messages between accepted network connections."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

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

    __table_args__ = (
        UniqueConstraint("sender_id", "client_key", name="uq_message_sender_client_key"),
        Index("message_thread_idx", "sender_id", "recipient_id", "created_at", "id"),
    )
