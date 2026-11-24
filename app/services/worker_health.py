"""Bounded progress deadlines, shared by workers, the supervisor and readiness checks.

Readiness compares last progress to each role's bounded work deadline. An
alive PID alone is not healthy progress. Share these limits with supervision
when changing network/FFmpeg/mail timeouts.
"""

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text

from app.core.config import settings
from app.models.workers import WorkerHeartbeat

WORKERS = ("recruitment", "reels", "notifications")


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def worker_names(value):
    names = tuple(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))
    if set(names) - set(WORKERS):
        raise ValueError("Choose recruitment, reels, or notifications.")
    return names


def work_deadline(name):
    # Shorter than the task lease: a stuck process must stop before another can take over.
    return {"recruitment": 75, "notifications": 90,
            "reels": settings.reels_process_timeout_seconds * 3 + 60}[name]


def report(db, name, instance_id, state, *, started_at, error_code="", at=None):
    timestamp = at or datetime.now(UTC)
    row = db.get(WorkerHeartbeat, (name, instance_id))
    if row is None:
        db.execute(delete(WorkerHeartbeat).where(
            WorkerHeartbeat.last_seen_at < timestamp - timedelta(days=7)
        ))
        row = WorkerHeartbeat(name=name, instance_id=instance_id, started_at=started_at)
        db.add(row)
    row.pid, row.state = os.getpid(), state
    row.last_seen_at = timestamp
    seconds = work_deadline(name) if state == "working" else 90 if state == "error" else 30
    row.expected_by = timestamp + timedelta(seconds=seconds)
    row.error_code = error_code[:80]
    db.commit()


def healthy(row, at=None):
    return bool(row and row.state in {"idle", "working"}
                and utc(row.expected_by) > (at or datetime.now(UTC)))


def snapshot(db, names=WORKERS, *, at=None):
    timestamp = at or datetime.now(UTC)
    rows = list(db.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.name.in_(names))))
    result = []
    for name in names:
        matching = [row for row in rows if row.name == name]
        row = max(matching, key=lambda r: (healthy(r, timestamp), utc(r.last_seen_at)),
                  default=None)
        ok = healthy(row, timestamp)
        state = row.state if row else "missing"
        if row and not ok and state in {"idle", "working"}:
            state = "stale"
        result.append({"name": name, "healthy": ok, "state": state,
                       "last_seen_at": row.last_seen_at if row else None})
    return result


def readiness(db):
    db.execute(text("SELECT 1"))
    names = worker_names(settings.required_workers)
    return all(row["healthy"] for row in snapshot(db, names)) if names else True
