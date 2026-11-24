"""Recovering worker loops and process supervision with bounded restart delays.

The notifications role also creates opportunity/lecture reminders, publishes
recurring activities, queues digests and maintains private message files. These
in-app jobs run even with mail disabled. Supervision restarts failed/stuck process
groups and reports progress to readiness. See docs/WORKER_OPERATIONS.md.
"""

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models.workers import WorkerHeartbeat
from app.services.worker_health import report, utc, worker_names

COMMANDS = {"recruitment": "recruitment-worker", "reels": "reels-worker",
            "notifications": "notification-worker"}


def _startup(name, db):
    if name == "recruitment":
        from app.services.recruitment import ensure_search_schedule

        ensure_search_schedule(db)
    elif name == "reels":
        from app.services.reel_worker import ffmpeg_binary

        ffmpeg_binary()


def _step(name, db):
    if name == "recruitment":
        from app.services.recruitment_worker import enqueue_due, run_next

        enqueue_due(db)
        return run_next(db)
    if name == "reels":
        from app.services.reel_worker import run_next

        return run_next(db)
    from app.services.account_mail import mail_available
    from app.services.community_participation import run_next_activity
    from app.services.education_notifications import queue_learning_reminders
    from app.services.notification_worker import run_next
    from app.services.opportunity_watch import generate_alerts
    from app.services.weekly_digest import enqueue
    from app.services.weekly_digest import run_next as run_digest

    generate_alerts(db)
    queue_learning_reminders(db)
    activity = run_next_activity(db)
    enqueue(db)
    if activity:
        return activity
    return (run_next(db) or run_digest(db)) if mail_available() else None


def _signals(stop):
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, lambda *_: stop.set())
    return previous


def run_worker(name, *, once=False, max_tasks=10, stop=None):
    """Run one role with fresh database sessions, progress reports, bounded backoff and graceful
    shutdown.
    """
    if name not in COMMANDS or not 1 <= max_tasks <= 100:
        raise ValueError("Invalid worker or task limit.")
    stop = stop or threading.Event()
    handlers = _signals(stop)
    raw_instance = os.environ.get("NURSE_NG_WORKER_INSTANCE", "")
    try:
        instance = uuid.UUID(hex=raw_instance).hex
    except ValueError:
        instance = uuid.uuid4().hex
    started = datetime.now(UTC)
    failures = completed = 0
    initialized = False
    next_file_cleanup = 0
    print(f"{name} worker started.", flush=True)
    try:
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    report(db, name, instance, "working", started_at=started)
                    if not initialized:
                        _startup(name, db)
                        initialized = True
                    if name == "notifications" and time.monotonic() >= next_file_cleanup:
                        from app.services.message_attachments import maintain_message_files

                        maintain_message_files(db)
                        next_file_cleanup = time.monotonic() + 300
                    outcome = _step(name, db)
                    report(db, name, instance, "idle", started_at=started)
                    if outcome is not None:
                        completed += 1
                        if name == "recruitment":
                            print(f"recruitment: {outcome.status}; {outcome.outcome}; "
                                  f"task={outcome.id}; {outcome.message}", flush=True)
                        else:
                            print(f"{name}: completed task {outcome[0]}; {outcome[1]}", flush=True)
                failures = 0
                if once and (outcome is None or completed >= max_tasks):
                    return 0
                if outcome is None:
                    stop.wait(3 if name == "reels" else 5)
            except Exception as exc:
                failures += 1
                # Exception text may contain credentials or private data; report only its class.
                error_code = type(exc).__name__
                print(f"{name}: worker pass failed ({error_code}); retrying.", flush=True)
                try:
                    with SessionLocal() as db:
                        report(db, name, instance, "error", started_at=started,
                               error_code=error_code)
                except SQLAlchemyError:
                    pass
                if once:
                    return 1
                stop.wait(min(60, 2 ** min(failures, 6)))
        return 0
    finally:
        try:
            with SessionLocal() as db:
                report(db, name, instance, "stopped", started_at=started)
        except SQLAlchemyError:
            pass
        for number, handler in handlers.items():
            signal.signal(number, handler)


@dataclass
class Child:
    name: str
    process: object = None
    instance: str = ""
    started: float = 0
    next_start: float = 0
    failures: int = 0


def stop_process(process):
    """Stop the entire worker group, including a network checker or FFmpeg child."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The leader can exit before one of its children; clean up the group in either case.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


class Supervisor:
    def __init__(self, names, *, popen=subprocess.Popen, clock=time.monotonic):
        self.children = [Child(name) for name in names]
        self.popen, self.clock = popen, clock

    def tick(self, db):
        moment, timestamp = self.clock(), datetime.now(UTC)
        try:
            reports = {(r.name, r.instance_id): r for r in db.scalars(select(WorkerHeartbeat))}
        except SQLAlchemyError:
            db.rollback()
            reports = None  # A database outage must not cause a restart storm.
        for child in self.children:
            if child.process is not None:
                row = reports.get((child.name, child.instance)) if reports is not None else None
                overdue = reports is not None and (
                    (row is not None and utc(row.expected_by) <= timestamp)
                    or (row is None and moment - child.started > 45)
                )
                if child.process.poll() is None and not overdue:
                    continue
                stop_process(child.process)
                if row is not None:
                    row.state = "stopped"
                    row.expected_by = timestamp
                    db.commit()
                if moment - child.started > 60:
                    child.failures = 0
                child.failures += 1
                child.next_start = moment + min(60, 2 ** min(child.failures, 6))
                child.process = None
                print(f"{child.name}: restarting after {'stale progress' if overdue else 'exit'}.",
                      flush=True)
            if child.process is None and moment >= child.next_start:
                child.instance = uuid.uuid4().hex
                env = {**os.environ, "NURSE_NG_WORKER_INSTANCE": child.instance}
                try:
                    child.process = self.popen(
                        [sys.executable, "-m", "app.cli", COMMANDS[child.name]],
                        env=env, start_new_session=True,
                    )
                    child.started = moment
                except OSError:
                    child.failures += 1
                    child.next_start = moment + min(60, 2 ** min(child.failures, 6))
                    print(f"{child.name}: process could not start; retrying.", flush=True)

    def close(self):
        for child in self.children:
            if child.process is not None:
                stop_process(child.process)


def run_supervisor(roles):
    """Start and recover configured worker process groups using their persisted progress deadlines.

    """
    names = worker_names(roles)
    if not names:
        raise ValueError("Choose at least one worker to supervise.")
    stop = threading.Event()
    handlers = _signals(stop)
    supervisor = Supervisor(names)
    print("Supervising workers: " + ", ".join(names), flush=True)
    try:
        while not stop.is_set():
            with SessionLocal() as db:
                supervisor.tick(db)
            stop.wait(2)
    finally:
        supervisor.close()
        for number, handler in handlers.items():
            signal.signal(number, handler)
    return 0
