"""Private saved opportunities and member-selected matching criteria."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SavedOpportunity(TimestampMixin, Base):
    """Private account/job bookmark with member-selected reminder state."""
    __tablename__ = "saved_opportunities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    remind: Mapped[bool] = mapped_column(Boolean, default=True)
    reminded_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpportunityPreference(TimestampMixin, Base):
    """Private matching interests and reminder choices used by opportunity alerts."""
    __tablename__ = "opportunity_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    keyword: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(100), default="")
    job_type: Mapped[str] = mapped_column(String(20), default="")
    country_code: Mapped[str] = mapped_column(String(2), default="NG")
    active_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
