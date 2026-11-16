"""Provider identities and short-lived, browser-bound sign-in handshakes."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SocialIdentity(Base):
    __tablename__ = "social_identities"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("user_id", "provider", name="social_user_provider"),)


class SocialAuthAttempt(Base):
    __tablename__ = "social_auth_attempts"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))
    nonce: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    auth_version: Mapped[int | None] = mapped_column(Integer)
    return_to: Mapped[str] = mapped_column(String(240), default="", server_default="")


class SocialEnrollment(Base):
    __tablename__ = "social_enrollments"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(254))
    full_name: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    return_to: Mapped[str] = mapped_column(String(240), default="", server_default="")
