"""Idempotent lecture reminders through the existing notification outbox.

The notification worker calls ``queue_learning_reminders`` even when SMTP is
disabled, because in-app reminders are useful independently of email. Receipts
use session ID + scheduled start + reminder window; retries cannot create a new
notice for the same learner/window. Changing a schedule therefore creates a new
receipt, while read/email delivery rechecks the current registration and time.
This module queues notices only. The established outbox owns mail delivery.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.education import EducatorProfile, LearningSession, SessionRegistration
from app.models.user import User, UserStatus
from app.services.notifications import emit


def notify_session_change(db, session, recipients, state):
    """Queue a current-state notice after a successful owner lifecycle change."""
    kinds = {
        "live": "learning_started",
        "cancelled": "learning_cancelled",
        "updated": "learning_updated",
    }
    if state not in kinds or not recipients:
        return
    timestamp = session.updated_at or datetime.now(UTC)
    emit(
        db,
        actor_id=session.educator_id,
        recipients=recipients,
        category="learning",
        kind=kinds[state],
        event_key=f"learning:{session.id}:{state}:{timestamp.isoformat()}",
        learning_session_id=session.id,
    )
    db.commit()


def queue_learning_reminders(db, *, now=None):
    """Queue the next applicable future-session reminder without fabricating delivery.

    A delayed worker queues the ten-minute reminder instead of simultaneously
    emitting an obsolete hour reminder. No reminder is sent after the start.
    Learners' opt-in email preference and active identity are enforced by emit
    and rechecked by the delivery worker. All due sessions are traversed in
    bounded fetch batches; truncating the first batch would repeatedly select
    already-reminded sessions and starve later sessions with the same start.
    """
    now = now or datetime.now(UTC)
    sessions = db.scalars(
        select(LearningSession)
        .join(EducatorProfile, EducatorProfile.user_id == LearningSession.educator_id)
        .join(User, User.id == EducatorProfile.user_id)
        .where(
            LearningSession.status == "scheduled",
            LearningSession.starts_at > now,
            LearningSession.starts_at <= now + timedelta(hours=1),
            EducatorProfile.status == "approved",
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
        .order_by(LearningSession.starts_at)
        .execution_options(yield_per=200)
    )
    queued_sessions = 0
    for session in sessions:
        start = (
            session.starts_at.replace(tzinfo=UTC)
            if session.starts_at.tzinfo is None
            else session.starts_at
        )
        minutes = 10 if start <= now + timedelta(minutes=10) else 60
        recipients = db.scalars(
            select(SessionRegistration.user_id).where(
                SessionRegistration.session_id == session.id,
                SessionRegistration.status == "reserved",
            )
        ).all()
        if recipients:
            emit(
                db,
                actor_id=session.educator_id,
                recipients=recipients,
                category="learning",
                kind="learning_reminder",
                event_key=f"learning:{session.id}:{start.isoformat()}:{minutes}",
                learning_session_id=session.id,
                deadline_at=start,
            )
            queued_sessions += 1
    db.commit()
    return queued_sessions
