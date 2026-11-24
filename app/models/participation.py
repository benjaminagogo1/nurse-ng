"""Member-owned support, recurring sessions, invitations and weekly digests."""

import uuid
from datetime import datetime

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
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MentorOffer(TimestampMixin, Base):
    """Opt-in public peer-support introduction with bounded concurrent-request capacity."""
    __tablename__ = "mentor_offers"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    topics: Mapped[str] = mapped_column(String(240))
    introduction: Mapped[str] = mapped_column(String(700))
    availability: Mapped[str] = mapped_column(String(200))
    capacity: Mapped[int] = mapped_column(Integer, default=3)
    accepting: Mapped[bool] = mapped_column(Boolean, default=True)
    show_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    __table_args__ = (CheckConstraint("capacity BETWEEN 1 AND 8", name="mentor_capacity"),)


class Mentorship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Private support request; open_pair prevents competing open requests for the same pair."""
    __tablename__ = "mentorship_requests"
    requester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(String(40))
    goal: Mapped[str] = mapped_column(String(1200))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    open_pair: Mapped[str | None] = mapped_column(String(65), unique=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_connections.id", ondelete="SET NULL")
    )
    __table_args__ = (
        CheckConstraint("requester_id != mentor_id", name="mentorship_not_self"),
        CheckConstraint(
            "status IN ('pending','accepted','declined','withdrawn','completed','ended')",
            name="mentorship_status",
        ),
    )


class MentorReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Private concern about one support request with staff review and duplicate-open protection."""
    __tablename__ = "mentorship_reports"
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentorship_requests.id", ondelete="CASCADE"), index=True
    )
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(30))
    details: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default="open")
    open_key: Mapped[str | None] = mapped_column(String(65), unique=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('open','resolved','dismissed')", name="mentor_report_status"),
    )


class ActivitySeries(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Host-owned recurring discussion schedule using a local wall-clock time and timezone."""
    __tablename__ = "community_activity_series"
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_topics.id", ondelete="CASCADE"), index=True
    )
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str] = mapped_column(Text)
    activity_format: Mapped[str] = mapped_column(String(20))
    interval_days: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    next_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint("interval_days IN (7,14,28)", name="activity_series_interval"),
        CheckConstraint(
            "activity_format IN ('discussion','practice','q-and-a')", name="activity_series_format"
        ),
    )


class ActivityOccurrence(Base):
    """One generated series session and its public discussion, unique within the schedule."""
    __tablename__ = "community_activity_occurrences"
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_activity_series.id", ondelete="CASCADE"), primary_key=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), unique=True
    )


class ActivityAttendance(Base):
    """Private choice to join a discussion activity; public display exposes aggregates only."""
    __tablename__ = "community_activity_attendance"
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberJourney(TimestampMixin, Base):
    """Private next-step goal, Helpful visibility choice and explicit dashboard dismissal
    timestamp.
    """
    __tablename__ = "member_journeys"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    goal: Mapped[str] = mapped_column(String(40), default="")
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    show_recognition: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class CommunityIntroduction(Base):
    """Saved public introduction reference and host welcome completion state."""
    __tablename__ = "community_introductions"
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    host_welcome: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferralInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Owner-scoped expiring/revocable personal link to an existing public destination."""
    __tablename__ = "referral_invitations"
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[str] = mapped_column(String(240))
    label: Mapped[str] = mapped_column(String(160))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (Index("referral_owner_created_idx", "owner_id", "created_at"),)


class ReferralVisit(Base):
    """Approximate browser visit receipt for an invitation, without IP/fingerprint identity."""
    __tablename__ = "referral_visits"
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("referral_invitations.id", ondelete="CASCADE"), primary_key=True
    )
    browser_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class MemberReferral(Base):
    """New-account attribution to a valid personal invitation, used for aggregate growth counts."""
    __tablename__ = "member_referrals"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("referral_invitations.id", ondelete="SET NULL"), index=True
    )
    inviter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("user_id != inviter_id", name="referral_not_self"),)


class DigestPreference(TimestampMixin, Base):
    """Verified-email weekly digest opt-in, content choices, weekday and timezone."""
    __tablename__ = "weekly_digest_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    questions: Mapped[bool] = mapped_column(Boolean, default=True)
    activities: Mapped[bool] = mapped_column(Boolean, default=True)
    opportunities: Mapped[bool] = mapped_column(Boolean, default=True)
    weekday: Mapped[int] = mapped_column(Integer, default=0)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos")
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    unsubscribe_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (CheckConstraint("weekday BETWEEN 0 AND 6", name="digest_weekday"),)


class WeeklyDigest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-account/local-week email receipt with expiring claim and bounded retry state."""
    __tablename__ = "weekly_digests"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    week_key: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(32))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # IDs only: live content and permissions are rechecked before sending.
    __table_args__ = (
        UniqueConstraint("user_id", "week_key", name="digest_user_week"),
        CheckConstraint(
            "state IN ('queued','sending','sent','skipped','failed')", name="weekly_digest_state"
        ),
    )
