"""Job listings posted by employer accounts."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class JobType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"


class WorkMode(StrEnum):
    ON_SITE = "on_site"
    REMOTE = "remote"
    FIELD = "field"


class JobStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    employer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    organization: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(120), default="")
    job_type: Mapped[str] = mapped_column(String(20), default=JobType.FULL_TIME)
    work_mode: Mapped[str] = mapped_column(String(20), default=WorkMode.ON_SITE)
    # Naira per month. Either bound may be left empty.
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.OPEN, index=True)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    employer: Mapped[User] = relationship(foreign_keys=[employer_user_id])


class JobApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Only the contact details explicitly shared on the application form."""

    __tablename__ = "job_applications"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    applicant_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    candidate_name: Mapped[str] = mapped_column(String(120))
    candidate_phone: Mapped[str] = mapped_column(String(16))
    candidate_email: Mapped[str] = mapped_column(String(254), default="")
    cover_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)

    job: Mapped[Job] = relationship()
    applicant: Mapped[User] = relationship()

    __table_args__ = (
        UniqueConstraint("job_id", "applicant_user_id", name="uniq_job_applicant"),
    )
