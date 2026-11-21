"""Lecture reminders use the existing outbox and recheck current learning access.

These journeys exercise real reservations, notification queries and the worker
step on isolated databases. The email path writes only to a temporary mailbox;
no test connects to SMTP, LiveKit or recording storage.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.education import (
    EducatorProfile,
    LearningEnrollment,
    LearningSession,
    SessionRegistration,
)
from app.models.notifications import Notification, NotificationPreference
from app.models.user import User
from app.services import education as learning
from app.services import notifications as notices
from app.services.education_notifications import notify_session_change, queue_learning_reminders
from app.services.notification_worker import run_next
from app.services.worker_runtime import _step


@pytest.fixture
def lecture(db_session):
    users = {
        name: User(
            phone=f"+23480955500{number:02}",
            hashed_password="unused-isolated-notification-test",
            is_staff=name == "staff",
        )
        for number, name in enumerate(("teacher", "learner", "staff"), 1)
    }
    db_session.add_all(users.values())
    db_session.commit()
    learning.apply_educator(
        db_session,
        users["teacher"],
        {
            "display_name": "Learning educator",
            "headline": "Nursing communication",
            "bio": "Discuss communication and support learning.",
        },
    )
    learning.review_educator(
        db_session,
        users["staff"],
        users["teacher"].id,
        "approved",
    )
    now = datetime.now(UTC)
    values = {
        "title": "Clear communication lecture",
        "description": "Explore clear communication with colleagues.",
        "starts_at": now + timedelta(minutes=30),
        "ends_at": now + timedelta(minutes=90),
        "timezone": "Africa/Lagos",
        "capacity": 10,
        "status": "scheduled",
    }
    session = learning.create_session(db_session, users["teacher"], values)
    learning.register_session(db_session, users["learner"], session.id)
    return users, session, values, now


def learning_notices(db):
    return list(db.scalars(select(Notification).where(Notification.category == "learning")))


def test_worker_generates_one_in_app_reminder_without_email(db_session, lecture, monkeypatch):
    users, session, _, _ = lecture
    monkeypatch.setattr(settings, "account_mail_backend", "disabled")
    assert _step("notifications", db_session) is None
    assert _step("notifications", db_session) is None
    queued = learning_notices(db_session)
    assert len(queued) == 1
    assert queued[0].email_state == "skipped" and queued[0].email_to == ""
    assert notices.unread_count(db_session, users["learner"]) == 1
    card = notices.card(db_session, queued[0])
    assert card["path"] == f"/learning/live/sessions/{session.id}"
    assert session.title in card["description"]


def test_reminder_windows_deduplicate_and_do_not_send_after_start(db_session, lecture):
    _, _, values, _ = lecture
    start = values["starts_at"]
    for now in (start - timedelta(minutes=45), start - timedelta(minutes=40)):
        queue_learning_reminders(db_session, now=now)
    assert len(learning_notices(db_session)) == 1
    for now in (start - timedelta(minutes=9), start - timedelta(minutes=1)):
        queue_learning_reminders(db_session, now=now)
    assert len(learning_notices(db_session)) == 2
    queue_learning_reminders(db_session, now=start)
    queue_learning_reminders(db_session, now=start + timedelta(minutes=5))
    assert len(learning_notices(db_session)) == 2


def test_reminder_batch_does_not_starve_later_due_lectures(db_session, lecture):
    """More than one query batch of simultaneous lectures must all be reminded."""
    users, _, values, now = lecture
    sessions = [
        LearningSession(
            educator_id=users["teacher"].id,
            **values,
        )
        for _ in range(201)
    ]
    db_session.add_all(sessions)
    db_session.flush()
    db_session.add_all(
        SessionRegistration(
            session_id=session.id,
            user_id=users["learner"].id,
            status="reserved",
        )
        for session in sessions
    )
    db_session.commit()
    queue_learning_reminders(db_session, now=now)
    assert len(learning_notices(db_session)) == 202
    queue_learning_reminders(db_session, now=now)
    assert len(learning_notices(db_session)) == 202


def test_rescheduling_hides_old_reminder_and_queues_current_start(db_session, lecture):
    users, session, values, now = lecture
    queue_learning_reminders(db_session, now=now)
    original = learning_notices(db_session)[0]
    learning.update_session(
        db_session,
        users["teacher"],
        session.id,
        {
            **values,
            "starts_at": values["starts_at"] + timedelta(minutes=10),
            "ends_at": values["ends_at"] + timedelta(minutes=10),
        },
    )
    assert notices.get_notice(db_session, users["learner"], original.id) is None
    queue_learning_reminders(db_session, now=now)
    assert len(learning_notices(db_session)) == 2
    visible, _ = notices.inbox_page(db_session, users["learner"], category="learning")
    assert len(visible) == 1 and visible[0].id != original.id


@pytest.mark.parametrize("revoked", ("withdrawn", "removed", "educator_paused", "teacher_inactive"))
def test_queued_reminder_rechecks_reservation_and_educator(db_session, lecture, revoked):
    users, session, _, now = lecture
    queue_learning_reminders(db_session, now=now)
    assert notices.unread_count(db_session, users["learner"]) == 1
    if revoked == "withdrawn":
        learning.cancel_registration(db_session, users["learner"], session.id)
    elif revoked == "removed":
        registration = db_session.get(SessionRegistration, (session.id, users["learner"].id))
        registration.status = "removed"
    elif revoked == "educator_paused":
        db_session.get(EducatorProfile, users["teacher"].id).status = "paused"
    else:
        users["teacher"].is_active = False
    db_session.commit()
    assert notices.unread_count(db_session, users["learner"]) == 0


@pytest.mark.parametrize("revoked", ("enrollment", "publication"))
def test_course_reminder_rechecks_enrollment_and_publication(db_session, lecture, revoked):
    users, _, values, now = lecture
    course = learning.create_course(
        db_session,
        users["teacher"],
        {
            "title": "Communication course",
            "summary": "Learn clear communication.",
            "description": "Study communication before the lecture.",
        },
    )
    module = learning.save_module(
        db_session, users["teacher"], course.id, {"title": "Introduction"}
    )
    learning.save_lesson(
        db_session,
        users["teacher"],
        module.id,
        {
            "title": "Listen first",
            "kind": "text",
            "content": "Listen before replying.",
        },
    )
    learning.set_course_status(db_session, users["teacher"], course.id, "published")
    learning.enroll(db_session, users["learner"], course.id)
    session = learning.create_session(
        db_session, users["teacher"], {**values, "course_id": course.id}
    )
    learning.register_session(db_session, users["learner"], session.id)
    queue_learning_reminders(db_session, now=now)
    queued = next(n for n in learning_notices(db_session) if n.learning_session_id == session.id)
    assert notices.get_notice(db_session, users["learner"], queued.id)
    if revoked == "enrollment":
        db_session.delete(db_session.get(LearningEnrollment, (course.id, users["learner"].id)))
        db_session.commit()
    else:
        learning.set_course_status(db_session, users["teacher"], course.id, "draft")
    assert notices.get_notice(db_session, users["learner"], queued.id) is None


def test_cancelled_session_notice_survives_released_reservation(db_session, lecture):
    users, session, _, now = lecture
    queue_learning_reminders(db_session, now=now)
    learning.change_session_state(db_session, users["teacher"], session.id, "cancelled")
    notify_session_change(db_session, session, [users["learner"].id], "cancelled")
    notify_session_change(db_session, session, [users["learner"].id], "cancelled")
    visible, _ = notices.inbox_page(db_session, users["learner"], category="learning")
    assert len(visible) == 1 and visible[0].kind == "learning_cancelled"
    assert "cancelled" in notices.card(db_session, visible[0])["heading"]


def test_email_reminder_rechecks_withdrawal_before_file_delivery(
    db_session,
    lecture,
    monkeypatch,
    tmp_path,
):
    users, session, _, now = lecture
    directory = tmp_path / "mail"
    monkeypatch.setattr(settings, "account_mail_backend", "file")
    monkeypatch.setattr(settings, "account_mail_dir", str(directory))
    monkeypatch.setattr(settings, "public_base_url", "https://nurse.example")
    learner = users["learner"]
    learner.email = "learner@example.org"
    learner.email_verified_at = now
    db_session.add(
        NotificationPreference(user_id=learner.id, category="learning", in_app=True, email=True)
    )
    db_session.commit()
    queue_learning_reminders(db_session, now=now)
    queued = learning_notices(db_session)[0]
    assert queued.email_state == "queued"
    learning.cancel_registration(db_session, learner, session.id)
    result = run_next(db_session)
    assert result is None or result[1] == "skipped"
    assert not list(directory.glob("*.eml"))
