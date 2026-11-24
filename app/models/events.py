"""Published community events and private member attendance choices."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CommunityEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Staff-authored event with publication state, scheduling and external meeting details."""
    __tablename__ = "community_events"

    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(240))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registration_url: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="scheduled", server_default="scheduled")
    creator_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="event_time_order"),
        CheckConstraint("status IN ('scheduled', 'cancelled')", name="event_status_valid"),
    )


class EventAttendance(Base):
    """Private member RSVP choice; it does not prove actual event attendance."""
    __tablename__ = "event_attendance"

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("community_events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
