"""Private resumable staging metadata; validated Reels still use existing media storage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OfflineUpload(TimestampMixin, Base):
    """Account-scoped resumable byte staging bound to session scope, expiry and publication
    receipt.
    """
    __tablename__ = "offline_uploads"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    upload_id: Mapped[UUID] = mapped_column(primary_key=True)
    session_scope: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    received: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    publication_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
