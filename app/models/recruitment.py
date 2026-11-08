"""Recruitment-source discovery is separate from trust and vacancy publication."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RecruitmentOrganization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recruitment_organizations"

    identity_key: Mapped[str] = mapped_column(String(160), unique=True)
    name: Mapped[str] = mapped_column(String(250))
    category: Mapped[str] = mapped_column(String(40), default="healthcare")
    country_code: Mapped[str] = mapped_column(String(2), default="", index=True)
    location: Mapped[str] = mapped_column(String(250), default="")
    website_url: Mapped[str] = mapped_column(String(2048), default="")


class RecruitmentSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recruitment_sources"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_organizations.id", ondelete="RESTRICT"), index=True
    )
    # Immutable in all service entry points. Redirect/canonical observations are separate.
    original_url: Mapped[str] = mapped_column(String(2048))
    url_key: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(30), default="recruitment_page")
    discovered_via: Mapped[str] = mapped_column(String(30))
    verification_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    approval_mode: Mapped[str] = mapped_column(String(20), default="", server_default="")
    activation_review: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    permission_status: Mapped[str] = mapped_column(String(20), default="unknown")
    reuse_basis: Mapped[str] = mapped_column(String(30), default="", server_default="")
    reuse_url_prefix: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    allow_collection: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    allow_snapshot_retention: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    allow_republication: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    automation_status: Mapped[str] = mapped_column(String(20), default="monitoring")
    collection_method: Mapped[str] = mapped_column(String(20), default="unconfirmed")
    collection_adapter: Mapped[str] = mapped_column(String(20), default="", server_default="")
    vacancy_url_prefix: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    deadline_timezone: Mapped[str] = mapped_column(String(80), default="", server_default="")
    access_notes: Mapped[str] = mapped_column(Text, default="")
    health_status: Mapped[str] = mapped_column(String(30), default="unchecked")
    observed_url: Mapped[str] = mapped_column(String(2048), default="")
    canonical_hint: Mapped[str] = mapped_column(String(2048), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_vacancy_discovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    organization: Mapped[RecruitmentOrganization] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("organization_id", "url_key", name="uq_recruitment_source_url"),
        CheckConstraint(
            "verification_status IN ('pending', 'approved', 'rejected', 'revoked')",
            name="ck_recruitment_source_verification",
        ),
        CheckConstraint(
            "permission_status IN ('unknown', 'permitted', 'limited', 'denied')",
            name="ck_recruitment_source_permission",
        ),
        CheckConstraint(
            "automation_status IN ('monitoring', 'paused', 'manual')",
            name="ck_recruitment_source_automation",
        ),
    )


class DiscoverySchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recruitment_discovery_schedules"

    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider: Mapped[str] = mapped_column(String(20))
    country_code: Mapped[str] = mapped_column(String(2), default="")
    query: Mapped[str] = mapped_column(String(300), default="")
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        CheckConstraint("provider IN ('ror', 'brave')", name="ck_discovery_provider"),
        CheckConstraint(
            "interval_hours >= 1 AND interval_hours <= 720", name="ck_discovery_interval"
        ),
    )


class DiscoveryTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recruitment_discovery_tasks"

    kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruitment_sources.id", ondelete="RESTRICT"), index=True
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruitment_discovery_schedules.id", ondelete="RESTRICT"), index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # NULL releases the key after completion; prevents duplicate pending work.
    active_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    # One network task at a time across workers, including different CLI processes.
    running_key: Mapped[str | None] = mapped_column(String(20), unique=True)
    lease_token: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    network_pause_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(String(500), default="")

    __table_args__ = (
        CheckConstraint("kind IN ('ror', 'brave', 'inspect')", name="ck_discovery_task_kind"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_discovery_task_status",
        ),
    )


class SourceEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "recruitment_source_events"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_sources.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruitment_discovery_tasks.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(40))
    reference_url: Mapped[str] = mapped_column(String(2048), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
