"""Original collection snapshots, normalized records and append-only processing history."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.models.recruitment import RecruitmentSource


class VacancySnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "vacancy_snapshots"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_sources.id", ondelete="RESTRICT"), index=True
    )
    original_url: Mapped[str] = mapped_column(String(2048))
    observed_url: Mapped[str] = mapped_column(String(2048))
    content_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[bytes] = mapped_column(LargeBinary)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    adapter: Mapped[str] = mapped_column(String(40), default="jsonld-v1")
    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_vacancy_snapshot"),)


class VacancyRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "vacancy_records"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_sources.id", ondelete="RESTRICT"), index=True
    )
    record_key: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy_snapshots.id", ondelete="RESTRICT")
    )
    raw_record: Mapped[dict] = mapped_column(JSON)
    normalized: Mapped[dict] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[RecruitmentSource] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("source_id", "record_key", name="uq_vacancy_source_record"),)


class VacancyEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "vacancy_events"

    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy_records.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy_snapshots.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
