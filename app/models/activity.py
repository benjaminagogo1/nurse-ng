"""Minimal, private activity history: one row per account and Nigerian calendar day."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserDailyActivity(Base):
    """Private aggregate of one account's usage on one Nigerian calendar day."""
    __tablename__ = "user_daily_activity"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (CheckConstraint("first_seen_at <= last_seen_at", name="activity_time_order"),)
