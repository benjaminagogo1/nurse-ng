"""Private, account-scoped progress for the guided interface tour."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserTour(Base):
    """Private account/version progress for the server-defined guided interface tour."""
    __tablename__ = "user_tours"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    step_key: Mapped[str | None] = mapped_column(String(48))
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('offered', 'active', 'completed', 'skipped')", name="tour_status"
        ),
        CheckConstraint("version > 0 AND revision >= 0", name="tour_versions"),
        CheckConstraint(
            "status != 'active' OR (run_id IS NOT NULL AND step_key IS NOT NULL "
            "AND started_at IS NOT NULL AND finished_at IS NULL)",
            name="tour_active_progress",
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'skipped') OR finished_at IS NOT NULL",
            name="tour_finished_time",
        ),
    )
