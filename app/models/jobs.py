"""Shared jobs for employer submissions and approved external recruitment sources."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.recruitment import RecruitmentSource
from app.models.user import User


class JobType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    FELLOWSHIP = "fellowship"
    GRADUATE_PROGRAMME = "graduate_programme"


class WorkMode(StrEnum):
    ON_SITE = "on_site"
    REMOTE = "remote"
    FIELD = "field"


class JobStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNCONFIRMED = "unconfirmed"
    WITHDRAWN = "withdrawn"


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    employer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    employer_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employer_organizations.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(250))
    organization: Mapped[str] = mapped_column(String(250))
    location: Mapped[str] = mapped_column(String(250), default="")
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruitment_sources.id", name="fk_job_recruitment_source", ondelete="RESTRICT"),
        index=True,
    )
    external_key: Mapped[str | None] = mapped_column(String(64))
    country_code: Mapped[str] = mapped_column(String(2), default="", server_default="", index=True)
    normalized_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    employer: Mapped[User | None] = relationship(foreign_keys=[employer_user_id])
    source: Mapped[RecruitmentSource | None] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("external_key", name="uq_jobs_external_key"),
        CheckConstraint(
            "(source_id IS NULL AND employer_user_id IS NOT NULL AND external_key IS NULL) OR "
            "(source_id IS NOT NULL AND employer_user_id IS NULL AND external_key IS NOT NULL)",
            name="ck_job_channel",
        ),
    )


class JobApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Only the contact details explicitly shared on the application form."""

    __tablename__ = "job_applications"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
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

    __table_args__ = (UniqueConstraint("job_id", "applicant_user_id", name="uniq_job_applicant"),)
