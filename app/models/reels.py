"""Reels extend community posts; conversations and moderation stay shared."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.community import CommunityPost


class Reel(TimestampMixin, Base):
    __tablename__ = "reels"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), primary_key=True
    )
    upload_key: Mapped[str] = mapped_column(String(36), unique=True)
    category: Mapped[str] = mapped_column(String(24), index=True)
    audience: Mapped[str] = mapped_column(String(16), default="nigeria", index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    captions: Mapped[str] = mapped_column(Text, default="")
    cover_seconds: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(String(300), default="")

    post: Mapped[CommunityPost] = relationship()

    __table_args__ = (
        CheckConstraint("state IN ('queued','processing','ready','failed')", name="reel_state"),
        CheckConstraint("audience IN ('nigeria','global')", name="reel_audience"),
        CheckConstraint(
            "category IN ('opportunities','career','learning','stories')", name="reel_category"
        ),
    )


class ReelSave(TimestampMixin, Base):
    """Private bookmarks, never a public list of a member's interests."""

    __tablename__ = "reel_saves"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.post_id", ondelete="CASCADE"), primary_key=True, index=True
    )
