"""Progress reports distinguish an idle worker from a stopped or stuck process."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkerHeartbeat(Base):
    """Role/instance progress report used for readiness and recovery of stalled workers."""
    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expected_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str] = mapped_column(String(80), default="")
