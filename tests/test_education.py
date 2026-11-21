"""Education ownership, grading, room permissions and provider evidence invariants.

These tests use isolated accounts/databases and never contact a live provider.
The capacity race uses independent transactions; the migration check exercises
an existing pre-education database through upgrade/downgrade without losing it.
"""

import os
import secrets
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import enable_sqlite_foreign_keys
from app.models.education import (
    EducatorReview,
    LearningAttendance,
    LearningEnrollment,
    LearningRecording,
    LearningSession,
    LearningWebhookReceipt,
    QuizAttempt,
    SessionMessage,
    SessionRegistration,
)
from app.models.user import User
from app.services import education as learning


@pytest.fixture
def education_accounts(db_session):
    users = {}
    for number, name in enumerate(["teacher", "student", "other", "staff"], 1):
        user = User(
            phone=f"+23480123456{number:02}",
            hashed_password="unused-domain-test-hash",
            is_staff=name == "staff",
        )
        db_session.add(user)
        users[name] = user
    db_session.commit()
    return users


def approve(db, users):
    teacher = users["teacher"]
    learning.apply_educator(
        db,
        teacher,
        {
            "display_name": "Nursing educator",
            "headline": "Teach and discuss nursing",
            "bio": "Practical teaching experience and learner support.",
            "subjects": "Nursing education, leadership",
        },
    )
    learning.review_educator(
        db, users["staff"], teacher.id, "approved", "Hosting application accepted."
    )
    return teacher


def create_course(db, teacher):
    return learning.create_course(
        db,
        teacher,
        {
            "title": "Nursing communication",
            "summary": "A course in clear communication.",
            "description": "Practice communication through reading and discussion.",
            "category": "Communication",
            "level": "beginner",
        },
    )


@pytest.fixture
def education_course(db_session, education_accounts):
    teacher = approve(db_session, education_accounts)
    course = create_course(db_session, teacher)
    module = learning.save_module(db_session, teacher, course.id, {"title": "Introduction"})
    lesson = learning.save_lesson(
        db_session,
        teacher,
        module.id,
        {
            "title": "Listen clearly",
            "kind": "text",
            "content": "Listen before replying.",
        },
    )
    return course, module, lesson


def session_values(**extra):
    starts = datetime.now(UTC) + timedelta(days=1)
    return {
        "title": "Clinical learning discussion",
        "description": "Learn with colleagues.",
        "objectives": "Understand the topic and ask questions.",
        "starts_at": starts,
        "ends_at": starts + timedelta(hours=1),
        "timezone": "Africa/Lagos",
        "capacity": 2,
        "status": "scheduled",
        "session_format": "lecture",
        **extra,
    }


def live_session(db, users, **extra):
    teacher = approve(db, users)
    starts = datetime.now(UTC) - timedelta(minutes=5)
    session = learning.create_session(
        db, teacher, session_values(starts_at=starts, ends_at=starts + timedelta(hours=1), **extra)
    )
    learning.register_session(db, users["student"], session.id)
    learning.change_session_state(db, teacher, session.id, "live")
    return session


def test_educator_approval_never_grants_staff_and_can_be_revoked(db_session, education_accounts):
    users = education_accounts
    profile = learning.apply_educator(
        db_session,
        users["teacher"],
        {
            "display_name": "Teacher",
            "headline": "Nursing educator",
            "bio": "Teach communication.",
        },
    )
    assert profile.status == "pending"
    assert not users["teacher"].is_staff
    with pytest.raises(learning.EducationError, match="approved educator"):
        create_course(db_session, users["teacher"])
    with pytest.raises(learning.EducationError, match="Staff approval"):
        learning.review_educator(db_session, users["other"], profile.user_id, "approved")
    validated, notes = learning.validate_educator_review(
        db_session, users["staff"], profile.user_id, "approved", "  Accepted.  "
    )
    assert validated is profile and notes == "Accepted."
    assert profile.status == "pending"
    assert db_session.scalar(select(func.count()).select_from(EducatorReview)) == 0
    learning.review_educator(db_session, users["staff"], profile.user_id, "approved")
    assert learning.can_teach(db_session, users["teacher"])
    assert not users["teacher"].is_staff
    learning.review_educator(db_session, users["staff"], profile.user_id, "paused")
    assert not learning.can_teach(db_session, users["teacher"])
    assert db_session.scalar(select(func.count()).select_from(EducatorReview)) == 2


def test_reapplication_identity_changes_require_review(db_session, education_accounts):
    teacher = approve(db_session, education_accounts)
    profile = learning.educator_for(db_session, teacher)
    unchanged = {
        key: getattr(profile, key) for key in ("display_name", "headline", "bio", "subjects")
    }
    assert not learning.educator_application_requires_review(db_session, teacher, unchanged)
    assert learning.educator_application_requires_review(
        db_session, teacher, {**unchanged, "display_name": "Changed teacher"}
    )
    assert profile.status == "approved"
    with pytest.raises(learning.EducationError):
        learning.educator_application_requires_review(
            db_session, teacher, {**unchanged, "display_name": ""}
        )
    assert profile.status == "approved"
    learning.apply_educator(
        db_session,
        teacher,
        {
            "display_name": "Changed teacher",
            "headline": "New subjects",
            "bio": "Revised application.",
        },
    )
    assert learning.educator_for(db_session, teacher).status == "pending"
    assert not learning.can_teach(db_session, teacher)


def test_room_closure_and_educator_revocation_share_the_callers_transaction(
    db_session, education_accounts
):
    users = education_accounts
    session = live_session(db_session, users)
    profile = learning.educator_for(db_session, users["teacher"])
    original_name = profile.display_name
    learning.apply_educator(
        db_session,
        users["teacher"],
        {
            "display_name": "Changed teaching identity",
            "headline": profile.headline,
            "bio": profile.bio,
            "subjects": profile.subjects,
        },
        commit=False,
    )
    assert profile.status == "pending"
    db_session.rollback()
    assert profile.status == "approved" and profile.display_name == original_name
    learning.change_session_state(db_session, users["teacher"], session.id, "ended", commit=False)
    learning.review_educator(
        db_session, users["staff"], profile.user_id, "paused", commit=False
    )
    assert session.status == "ended" and profile.status == "paused"
    db_session.rollback()
    assert session.status == "live" and profile.status == "approved"
    learning.change_session_state(db_session, users["teacher"], session.id, "ended", commit=False)
    learning.review_educator(
        db_session, users["staff"], profile.user_id, "paused", commit=False
    )
    db_session.commit()
    db_session.expire_all()
    assert session.status == "ended" and profile.status == "paused"


def test_course_drafts_and_lessons_have_separate_access_boundaries(
    db_session, education_accounts, education_course
):
    course, _, lesson = education_course
    users = education_accounts
    assert learning.list_courses(db_session) == []
    assert learning.get_course(db_session, course.id, users["teacher"]).id == course.id
    for user in [None, users["student"], users["other"]]:
        with pytest.raises(learning.EducationError) as error:
            learning.get_course(db_session, course.id, user)
        assert error.value.status_code == 404
    learning.set_course_status(db_session, users["teacher"], course.id, "published")
    assert [row.id for row in learning.list_courses(db_session)] == [course.id]
    with pytest.raises(learning.EducationError, match="Enroll"):
        learning.get_lesson(db_session, lesson.id, users["student"])
    with pytest.raises(learning.EducationError, match="approved educator or staff"):
        learning.update_course(db_session, users["other"], course.id, {"title": "Stolen"})
    learning.enroll(db_session, users["student"], course.id)
    assert (
        learning.get_lesson(db_session, lesson.id, users["student"]).content
        == "Listen before replying."
    )


def test_enrollment_and_completion_retries_preserve_one_record(
    db_session, education_accounts, education_course
):
    course, _, lesson = education_course
    teacher, student = education_accounts["teacher"], education_accounts["student"]
    learning.set_course_status(db_session, teacher, course.id, "published")
    for _ in range(2):
        learning.enroll(db_session, student, course.id)
        learning.mark_lesson_complete(db_session, student, lesson.id)
    progress = learning.course_progress(db_session, student, course.id)
    assert progress["completed"] == progress["total"] == 1
    assert progress["completed_at"] is not None
    assert db_session.scalar(select(func.count()).select_from(LearningEnrollment)) == 1
    learning.save_module(db_session, teacher, course.id, {"title": "Next module"})
    assert learning.course_progress(db_session, student, course.id)["completed_at"] is None


def test_empty_course_and_empty_quiz_cannot_be_published(db_session, education_accounts):
    teacher = approve(db_session, education_accounts)
    course = create_course(db_session, teacher)
    with pytest.raises(learning.EducationError, match="at least one lesson"):
        learning.set_course_status(db_session, teacher, course.id, "published")
    module = learning.save_module(db_session, teacher, course.id, {"title": "Quiz module"})
    learning.save_lesson(
        db_session, teacher, module.id, {"title": "Knowledge check", "kind": "quiz"}
    )
    with pytest.raises(learning.EducationError, match="Add questions"):
        learning.set_course_status(db_session, teacher, course.id, "published")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/resource",
        "javascript:alert(1)",
        "https://localhost/",
        "https://127.0.0.1/",
        "https://192.168.1.2/",
        "https://user:secret@example.org/",
        "https://example.org:8443/",
        "https://example.org/\nheader",
    ],
)
def test_learning_resources_reject_unsafe_urls(url):
    with pytest.raises(learning.EducationError, match="public HTTPS"):
        learning.resource_url(url)


def test_resource_lesson_validation_and_ordering(db_session, education_accounts, education_course):
    _, module, first = education_course
    teacher = education_accounts["teacher"]
    with pytest.raises(learning.EducationError, match="public HTTPS"):
        learning.save_lesson(
            db_session, teacher, module.id, {"title": "Resource", "kind": "resource"}
        )
    resource = learning.save_lesson(
        db_session,
        teacher,
        module.id,
        {"title": "Resource", "kind": "resource", "resource_url": "https://example.org/reading"},
    )
    assert resource.position == first.position + 1
    with pytest.raises(learning.EducationError, match="position"):
        learning.save_lesson(
            db_session,
            teacher,
            module.id,
            {"title": "Duplicate", "kind": "text", "content": "Content", "position": 1},
        )
    assert (
        len(learning.course_content(db_session, first.module.course_id, teacher)[0]["lessons"]) == 2
    )


def test_quiz_answer_keys_are_private_and_scores_are_computed(
    db_session, education_accounts, education_course
):
    course, module, reading = education_course
    teacher, student = education_accounts["teacher"], education_accounts["student"]
    quiz = learning.save_lesson(
        db_session, teacher, module.id, {"title": "Knowledge check", "kind": "quiz"}
    )
    question = learning.save_quiz_question(
        db_session,
        teacher,
        quiz.id,
        {
            "prompt": "What comes first?",
            "options": ["Listening", "Interrupting"],
            "correct_index": 0,
            "explanation": "Listen to understand.",
        },
    )
    learning.set_course_status(db_session, teacher, course.id, "published")
    learning.enroll(db_session, student, course.id)
    safe = learning.quiz_questions(db_session, student, quiz.id)
    assert set(safe[0]) == {"id", "prompt", "options"}
    with pytest.raises(learning.EducationError) as error:
        learning.quiz_questions(db_session, student, quiz.id, include_answers=True)
    assert error.value.status_code == 403
    assert (
        learning.quiz_questions(db_session, teacher, quiz.id, include_answers=True)[0][
            "correct_index"
        ]
        == 0
    )
    with pytest.raises(learning.EducationError, match="Pass the lesson quiz"):
        learning.mark_lesson_complete(db_session, student, quiz.id)
    failed = learning.submit_quiz(
        db_session, student, quiz.id, {str(question.id): 1}, "failed-attempt"
    )
    assert (failed.score, failed.total, failed.passed) == (0, 1, False)
    assert learning.course_progress(db_session, student, course.id)["completed"] == 0
    passed = learning.submit_quiz(
        db_session, student, quiz.id, {str(question.id): 0}, "passed-attempt"
    )
    assert passed.passed
    again = learning.submit_quiz(
        db_session, student, quiz.id, {str(question.id): 0}, "passed-attempt"
    )
    assert again.id == passed.id
    with pytest.raises(learning.EducationError, match="already used"):
        learning.submit_quiz(db_session, student, quiz.id, {str(question.id): 1}, "passed-attempt")
    learning.mark_lesson_complete(db_session, student, reading.id)
    assert learning.course_progress(db_session, student, course.id)["percent"] == 100
    assert db_session.scalar(select(func.count()).select_from(QuizAttempt)) == 2
    assert learning.quiz_attempt_feedback(db_session, student, failed) == {
        question.id: {"correct": False, "explanation": "Listen to understand."}
    }
    assert learning.quiz_attempt_feedback(db_session, student, passed) == {
        question.id: {"correct": True, "explanation": "Listen to understand."}
    }
    with pytest.raises(learning.EducationError) as private_feedback:
        learning.quiz_attempt_feedback(db_session, education_accounts["other"], passed)
    assert private_feedback.value.status_code == 403
    learning.set_course_status(db_session, teacher, course.id, "draft")
    with pytest.raises(learning.EducationError) as withdrawn_feedback:
        learning.quiz_attempt_feedback(db_session, student, passed)
    assert withdrawn_feedback.value.status_code == 404


def test_quiz_requires_complete_current_answers_and_enrollment(
    db_session, education_accounts, education_course
):
    course, module, _ = education_course
    teacher, student = education_accounts["teacher"], education_accounts["student"]
    quiz = learning.save_lesson(db_session, teacher, module.id, {"title": "Quiz", "kind": "quiz"})
    question = learning.save_quiz_question(
        db_session,
        teacher,
        quiz.id,
        {"prompt": "Pick one", "options": "First\nSecond", "correct_index": 1},
    )
    learning.set_course_status(db_session, teacher, course.id, "published")
    with pytest.raises(learning.EducationError, match="Enroll"):
        learning.submit_quiz(db_session, student, quiz.id, {str(question.id): 1})
    learning.enroll(db_session, student, course.id)
    for answers in [
        {},
        {str(question.id): -1},
        {str(question.id): 2},
        {str(question.id): 1, str(uuid4()): 0},
        {str(question.id): 1.5},
    ]:
        with pytest.raises(learning.EducationError):
            learning.submit_quiz(db_session, student, quiz.id, answers)


def test_capacity_reservations_are_idempotent_and_released_once(db_session, education_accounts):
    users = education_accounts
    teacher = approve(db_session, users)
    session = learning.create_session(db_session, teacher, session_values(capacity=1))
    for _ in range(2):
        learning.register_session(db_session, users["student"], session.id)
    assert session.reserved_count == 1
    with pytest.raises(learning.EducationError, match="full"):
        learning.register_session(db_session, users["other"], session.id)
    for _ in range(2):
        learning.cancel_registration(db_session, users["student"], session.id)
    assert db_session.get(LearningSession, session.id).reserved_count == 0
    learning.register_session(db_session, users["other"], session.id)
    assert db_session.get(LearningSession, session.id).reserved_count == 1


def test_course_sessions_require_enrollment_and_foreign_course_is_rejected(
    db_session, education_accounts, education_course
):
    course, _, _ = education_course
    users = education_accounts
    with pytest.raises(learning.EducationError, match="Publish"):
        learning.create_session(db_session, users["teacher"], session_values(course_id=course.id))
    learning.set_course_status(db_session, users["teacher"], course.id, "published")
    session = learning.create_session(
        db_session, users["teacher"], session_values(course_id=course.id)
    )
    with pytest.raises(learning.EducationError, match="Enroll"):
        learning.register_session(db_session, users["student"], session.id)
    learning.enroll(db_session, users["student"], course.id)
    assert learning.register_session(db_session, users["student"], session.id).status == "reserved"


def test_room_lifecycle_rejects_early_start_and_terminal_reopening(db_session, education_accounts):
    teacher = approve(db_session, education_accounts)
    session = learning.create_session(db_session, teacher, session_values())
    with pytest.raises(learning.EducationError, match="fifteen minutes"):
        learning.change_session_state(db_session, teacher, session.id, "live")
    learning.change_session_state(
        db_session,
        teacher,
        session.id,
        "live",
        now=learning.utc(session.starts_at) - timedelta(minutes=10),
    )
    learning.change_session_state(db_session, teacher, session.id, "ended")
    with pytest.raises(learning.EducationError, match="state change"):
        learning.change_session_state(db_session, teacher, session.id, "live")


def test_lecture_speaking_and_removed_access_are_host_controlled(db_session, education_accounts):
    users = education_accounts
    session = live_session(db_session, users)
    assert learning.join_session(db_session, users["teacher"], session.id)["role"] == "host"
    assert not learning.join_session(db_session, users["student"], session.id)["can_publish"]
    learning.set_hand_raise(db_session, users["student"], session.id, True)
    with pytest.raises(learning.EducationError):
        learning.moderate_participant(
            db_session, users["student"], session.id, users["student"].id, "allow_speaking"
        )
    learning.moderate_participant(
        db_session, users["teacher"], session.id, users["student"].id, "allow_speaking"
    )
    assert learning.join_session(db_session, users["student"], session.id)["can_publish"]
    learning.moderate_participant(
        db_session, users["teacher"], session.id, users["student"].id, "revoke_speaking"
    )
    assert not learning.join_session(db_session, users["student"], session.id)["can_publish"]
    learning.moderate_participant(
        db_session, users["teacher"], session.id, users["student"].id, "remove"
    )
    for action in [
        lambda: learning.join_session(db_session, users["student"], session.id),
        lambda: learning.register_session(db_session, users["student"], session.id),
    ]:
        with pytest.raises(learning.EducationError):
            action()
    assert db_session.get(LearningSession, session.id).reserved_count == 0


def test_discussion_mode_messages_and_moderation_are_private(db_session, education_accounts):
    users = education_accounts
    session = live_session(db_session, users, session_format="discussion")
    assert learning.join_session(db_session, users["student"], session.id)["can_publish"]
    learning.moderate_participant(
        db_session, users["teacher"], session.id, users["student"].id, "revoke_speaking"
    )
    assert not learning.join_session(db_session, users["student"], session.id)["can_publish"]
    with pytest.raises(learning.EducationError):
        learning.send_session_message(
            db_session, users["other"], session.id, "Unregistered chat", "chat"
        )
    question = learning.send_session_message(
        db_session, users["student"], session.id, "How can I practice?"
    )
    learning.moderate_message(
        db_session, users["teacher"], question.id, "answer", "Practice listening."
    )
    assert (
        learning.session_messages(db_session, users["student"], session.id)[0].answer
        == "Practice listening."
    )
    learning.moderate_message(db_session, users["teacher"], question.id, "hide")
    assert learning.session_messages(db_session, users["student"], session.id) == []
    assert (
        learning.session_messages(db_session, users["teacher"], session.id, include_hidden=True)[
            0
        ].id
        == question.id
    )
    with pytest.raises(learning.EducationError):
        learning.session_messages(db_session, users["student"], session.id, include_hidden=True)
    assert db_session.scalar(select(func.count()).select_from(SessionMessage)) == 1


def test_cancellation_releases_seats_and_prevents_joining(db_session, education_accounts):
    users = education_accounts
    session = live_session(db_session, users)
    learning.change_session_state(db_session, users["teacher"], session.id, "cancelled")
    assert session.reserved_count == 0
    assert (
        db_session.get(SessionRegistration, (session.id, users["student"].id)).status == "cancelled"
    )
    with pytest.raises(learning.EducationError):
        learning.join_session(db_session, users["student"], session.id)


def provider_event(db, session, identifier, kind, payload=None, occurred=None):
    return learning.apply_provider_event(
        db,
        identifier,
        kind,
        f"nurse-learning-{session.id}",
        payload or {},
        occurred or datetime.now(UTC),
    )


def test_provider_attendance_is_deduplicated_and_unknown_identities_ignored(
    db_session, education_accounts
):
    users = education_accounts
    session = live_session(db_session, users)
    joined = datetime.now(UTC) - timedelta(minutes=2)
    payload = {"participant": {"identity": str(users["student"].id), "sid": "PA_connection"}}
    assert not provider_event(db_session, session, "join-1", "participant_joined", payload, joined)[
        "duplicate"
    ]
    assert provider_event(db_session, session, "join-1", "participant_joined", payload, joined)[
        "duplicate"
    ]
    provider_event(
        db_session, session, "leave-1", "participant_left", payload, joined + timedelta(seconds=60)
    )
    summary = learning.attendance_summary(db_session, users["student"], session.id)
    assert summary["seconds"] == 60
    assert summary["basis"] == "provider-confirmed"
    assert db_session.scalar(select(func.count()).select_from(LearningAttendance)) == 1
    provider_event(
        db_session,
        session,
        "unregistered",
        "participant_joined",
        {"participant": {"identity": str(users["other"].id), "sid": "PA_other"}},
        joined,
    )
    assert db_session.scalar(select(func.count()).select_from(LearningAttendance)) == 1
    with pytest.raises(learning.EducationError, match="conflicting contents"):
        provider_event(
            db_session,
            session,
            "join-1",
            "participant_joined",
            {"participant": {"identity": str(users["teacher"].id), "sid": "PA_connection"}},
            joined,
        )


def test_out_of_order_attendance_and_overlapping_tabs_do_not_inflate_time(
    db_session, education_accounts
):
    users = education_accounts
    session = live_session(db_session, users)
    joined = datetime.now(UTC) - timedelta(minutes=2)
    first = {"participant": {"identity": str(users["student"].id), "sid": "PA_first"}}
    second = {"participant": {"identity": str(users["student"].id), "sid": "PA_second"}}
    provider_event(
        db_session, session, "first-left", "participant_left", first, joined + timedelta(seconds=60)
    )
    provider_event(db_session, session, "first-joined", "participant_joined", first, joined)
    provider_event(
        db_session,
        session,
        "second-joined",
        "participant_joined",
        second,
        joined + timedelta(seconds=30),
    )
    provider_event(
        db_session,
        session,
        "second-left",
        "participant_left",
        second,
        joined + timedelta(seconds=90),
    )
    assert learning.attendance_summary(db_session, users["student"], session.id)["seconds"] == 90


def test_provider_recordings_require_private_object_key_and_authorized_playback(
    db_session, education_accounts
):
    users = education_accounts
    session = live_session(db_session, users, recording_enabled=True)
    key = f"learning/{session.id}/recording-test.mp4"
    recording = learning.register_recording(
        db_session, users["teacher"], session.id, {"egress_id": "EG_private", "object_key": key}
    )
    with pytest.raises(learning.EducationError):
        learning.recording_for(db_session, users["student"], recording.id)
    payload = {
        "egressInfo": {
            "egressId": "EG_private",
            "status": 3,
            "fileResults": [{"filename": key, "duration": 60_000_000_000}],
        }
    }
    provider_event(db_session, session, "recorded", "egress_ended", payload)
    assert learning.recording_for(db_session, users["student"], recording.id).duration_seconds == 60
    with pytest.raises(learning.EducationError):
        learning.recording_for(db_session, users["other"], recording.id)
    provider_event(
        db_session,
        session,
        "late-start",
        "egress_started",
        {
            "egressInfo": {
                "egressId": "EG_private",
                "status": 1,
                "fileResults": [{"filename": key, "duration": 0}],
            }
        },
    )
    assert recording.status == "complete"
    assert recording.duration_seconds == 60
    completed_at = recording.completed_at
    provider_event(
        db_session,
        session,
        "late-failure",
        "egress_ended",
        {
            "egressInfo": {
                "egressId": "EG_private",
                "status": 4,
                "fileResults": [{"filename": f"learning/{session.id}/failed.mp4"}],
            }
        },
    )
    assert recording.status == "complete"
    assert recording.storage_key == key
    assert recording.completed_at == completed_at
    provider_event(
        db_session,
        session,
        "unsafe-recorded",
        "egress_ended",
        {
            "egressInfo": {
                "egressId": "EG_unsafe",
                "status": 3,
                "fileResults": [{"filename": "https://external.example/recording.mp4"}],
            }
        },
    )
    unsafe = db_session.scalar(
        select(LearningRecording).where(LearningRecording.provider_egress_id == "EG_unsafe")
    )
    assert not unsafe.storage_key
    with pytest.raises(learning.EducationError):
        learning.recording_for(db_session, users["student"], unsafe.id)


def test_room_finished_webhook_closes_connections_without_reopening_terminal_state(
    db_session, education_accounts
):
    users = education_accounts
    session = live_session(db_session, users)
    when = datetime.now(UTC) - timedelta(seconds=30)
    provider_event(
        db_session,
        session,
        "connect",
        "participant_joined",
        {"participant": {"identity": str(users["student"].id), "sid": "PA_close"}},
        when,
    )
    provider_event(
        db_session, session, "room-finished", "room_finished", occurred=when + timedelta(seconds=20)
    )
    assert session.status == "ended"
    assert learning.attendance_summary(db_session, users["student"], session.id)["seconds"] == 20
    provider_event(db_session, session, "late-room-started", "room_started", occurred=when)
    assert session.status == "ended"
    assert db_session.scalar(select(func.count()).select_from(LearningWebhookReceipt)) == 3


def test_capacity_race_with_independent_transactions_never_overbooks(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'capacity.db'}", connect_args={"timeout": 15})
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        users = {}
        for number, name in enumerate(["teacher", "student", "other", "staff"], 1):
            user = User(
                phone=f"+23480234567{number:02}", hashed_password="unused", is_staff=name == "staff"
            )
            db.add(user)
            users[name] = user
        db.commit()
        teacher = approve(db, users)
        session = learning.create_session(db, teacher, session_values(capacity=1))
        identifiers = [users["student"].id, users["other"].id]
        session_id = session.id

    def reserve(identifier):
        with Session(engine, expire_on_commit=False) as db:
            try:
                learning.register_session(db, db.get(User, identifier), session_id)
                return True
            except learning.EducationError:
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, identifiers))
    with Session(engine) as db:
        assert results.count(True) == 1
        assert db.get(LearningSession, session_id).reserved_count == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(SessionRegistration)
                .where(SessionRegistration.status == "reserved")
            )
            == 1
        )
    engine.dispose()


def test_education_migration_upgrade_downgrade_and_existing_notification_survive(tmp_path):
    path = tmp_path / "migration.db"
    env = dict(os.environ)
    env.update(
        {
            "NURSE_NG_ENVIRONMENT": "development",
            "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
            "NURSE_NG_DATABASE_URL": f"sqlite:///{path}",
            "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
            "NURSE_NG_RECRUITMENT_SEARXNG_URLS": "",
        }
    )

    def migrate(target):
        result = subprocess.run(
            ["venv/bin/alembic", "upgrade", target],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    migrate("e6480j0f6527")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE education_migration_sentinel (value TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO education_migration_sentinel VALUES ('preserved')"))
        user_id, notification_id = uuid4().hex, uuid4().hex
        conn.execute(
            text(
                "INSERT INTO users (id,phone,hashed_password,status,phone_verified,mfa_enabled,"
                "is_active,is_staff) VALUES (:id,'+2348034567890','unused','active',0,0,1,0)"
            ),
            {"id": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO notifications (id,recipient_id,actor_id,category,kind,event_key,"
                "in_app,application_status,email_to,email_state,email_attempts) "
                "VALUES (:id,:user,:user,'community','reply','old-preserved',1,'','','skipped',0)"
            ),
            {"id": notification_id, "user": user_id},
        )
    migrate("head")
    assert "learning_sessions" in inspect(engine).get_table_names()
    assert any(
        column["name"] == "learning_session_id"
        for column in inspect(engine).get_columns("notifications")
    )
    result = subprocess.run(
        ["venv/bin/alembic", "downgrade", "e6480j0f6527"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "learning_sessions" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT value FROM education_migration_sentinel")).scalar()
            == "preserved"
        )
        assert conn.execute(text("SELECT event_key FROM notifications")).scalar() == "old-preserved"
    migrate("head")
    assert "learning_recordings" in inspect(engine).get_table_names()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO educator_profiles (user_id,display_name,headline,bio) "
                "VALUES (:user,'Existing educator','Teaching','Retained teaching application')"
            ),
            {"user": user_id},
        )
    refused = subprocess.run(
        ["venv/bin/alembic", "downgrade", "e6480j0f6527"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert refused.returncode != 0
    assert "Education data exists; export it before downgrading." in refused.stderr
    with engine.connect() as conn:
        assert conn.execute(text("SELECT display_name FROM educator_profiles")).scalar() == (
            "Existing educator"
        )
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "e6480k1e9038"
        )
    engine.dispose()


def test_session_catalog_join_and_draft_privacy(db_session, education_accounts, education_course):
    course, _, _ = education_course
    users = education_accounts
    standalone = learning.create_session(db_session, users["teacher"], session_values())
    draft = learning.create_session(db_session, users["teacher"], session_values(status="draft"))
    learning.set_course_status(db_session, users["teacher"], course.id, "published")
    course_session = learning.create_session(
        db_session, users["teacher"], session_values(course_id=course.id)
    )
    assert {row.id for row in learning.list_sessions(db_session)} == {
        standalone.id,
        course_session.id,
    }
    assert draft.id in {
        row.id for row in learning.list_sessions(db_session, users["teacher"], owned=True)
    }
    with pytest.raises(learning.EducationError) as error:
        learning.get_session(db_session, draft.id, users["student"])
    assert error.value.status_code == 404


def test_edited_lesson_content_invalidates_obsolete_completion(
    db_session, education_accounts, education_course
):
    course, module, lesson = education_course
    teacher, student = education_accounts["teacher"], education_accounts["student"]
    learning.set_course_status(db_session, teacher, course.id, "published")
    learning.enroll(db_session, student, course.id)
    learning.mark_lesson_complete(db_session, student, lesson.id)
    learning.save_lesson(
        db_session,
        teacher,
        module.id,
        {"title": lesson.title, "kind": "text", "content": "A revised lesson."},
        lesson_id=lesson.id,
    )
    progress = learning.course_progress(db_session, student, course.id)
    assert progress["completed"] == 0
    assert progress["completed_at"] is None


def test_paused_educator_cannot_be_started_by_staff(db_session, education_accounts):
    users = education_accounts
    teacher = approve(db_session, users)
    session = learning.create_session(db_session, teacher, session_values())
    learning.review_educator(db_session, users["staff"], teacher.id, "paused")
    with pytest.raises(learning.EducationError, match="currently be approved"):
        learning.change_session_state(
            db_session, users["staff"], session.id, "live", allow_early=True
        )


def test_registration_retry_after_end_is_rejected(db_session, education_accounts):
    users = education_accounts
    session = live_session(db_session, users)
    learning.change_session_state(db_session, users["teacher"], session.id, "ended")
    with pytest.raises(learning.EducationError, match="no longer accepts"):
        learning.register_session(db_session, users["student"], session.id)


def test_withdrawn_course_session_cannot_be_opened_or_reopened_by_provider(
    db_session, education_accounts, education_course
):
    course, _, _ = education_course
    teacher = education_accounts["teacher"]
    learning.set_course_status(db_session, teacher, course.id, "published")
    starts = datetime.now(UTC) - timedelta(minutes=5)
    session = learning.create_session(
        db_session,
        teacher,
        session_values(course_id=course.id, starts_at=starts, ends_at=starts + timedelta(hours=1)),
    )
    learning.set_course_status(db_session, teacher, course.id, "draft")
    with pytest.raises(learning.EducationError, match="associated course"):
        learning.change_session_state(db_session, teacher, session.id, "live")
    db_session.rollback()
    provider_event(db_session, session, "withdrawn-room-start", "room_started")
    assert session.status == "scheduled"


def test_curriculum_becomes_private_when_new_quiz_is_unfinished(
    db_session, education_accounts, education_course
):
    course, module, _ = education_course
    teacher = education_accounts["teacher"]
    learning.set_course_status(db_session, teacher, course.id, "published")
    quiz = learning.save_lesson(
        db_session, teacher, module.id, {"title": "New quiz", "kind": "quiz"}
    )
    assert course.status == "draft"
    assert learning.list_courses(db_session) == []
    learning.save_quiz_question(
        db_session,
        teacher,
        quiz.id,
        {"prompt": "Pick one", "options": ["First", "Second"], "correct_index": 0},
    )
    learning.set_course_status(db_session, teacher, course.id, "published")
    assert course.status == "published"


def test_deleting_last_lesson_withdraws_published_curriculum(
    db_session, education_accounts, education_course
):
    course, _, lesson = education_course
    teacher = education_accounts["teacher"]
    learning.set_course_status(db_session, teacher, course.id, "published")
    learning.delete_learning_item(db_session, teacher, "lesson", lesson.id)
    assert course.status == "draft"


def test_quiz_revisions_reject_stale_forms_and_preserve_old_attempt_evidence(
    db_session, education_accounts, education_course
):
    course, module, _ = education_course
    teacher, student = education_accounts["teacher"], education_accounts["student"]
    lesson = learning.save_lesson(db_session, teacher, module.id, {"title": "Quiz", "kind": "quiz"})
    question = learning.save_quiz_question(
        db_session,
        teacher,
        lesson.id,
        {"prompt": "Which answer?", "options": ["First", "Second"], "correct_index": 0},
    )
    learning.set_course_status(db_session, teacher, course.id, "published")
    learning.enroll(db_session, student, course.id)
    original_revision = learning.quiz_revision(db_session, student, lesson.id)
    attempt = learning.submit_quiz(
        db_session,
        student,
        lesson.id,
        {str(question.id): 0},
        "original",
        lesson_revision=original_revision,
    )
    assert attempt.passed and attempt.lesson_revision == original_revision
    learning.save_quiz_question(
        db_session,
        teacher,
        lesson.id,
        {"prompt": question.prompt, "options": question.options, "correct_index": 1},
        question_id=question.id,
    )
    assert lesson.revision == original_revision + 1
    assert attempt.lesson_revision != lesson.revision
    with pytest.raises(learning.EducationError) as stale_feedback:
        learning.quiz_attempt_feedback(db_session, student, attempt)
    assert stale_feedback.value.status_code == 409
    assert learning.course_progress(db_session, student, course.id)["completed"] == 0
    with pytest.raises(learning.EducationError) as stale:
        learning.submit_quiz(
            db_session,
            student,
            lesson.id,
            {str(question.id): 0},
            "old-form",
            lesson_revision=original_revision,
        )
    assert stale.value.status_code == 409
    with pytest.raises(learning.EducationError) as reused:
        learning.submit_quiz(
            db_session,
            student,
            lesson.id,
            {str(question.id): 1},
            "original",
            lesson_revision=lesson.revision,
        )
    assert reused.value.status_code == 409
    current = learning.submit_quiz(
        db_session,
        student,
        lesson.id,
        {str(question.id): 1},
        "current",
        lesson_revision=lesson.revision,
    )
    assert current.passed and current.lesson_revision == lesson.revision


def test_question_deletion_increments_revision_and_withdraws_empty_quiz(
    db_session, education_accounts, education_course
):
    course, module, _ = education_course
    teacher = education_accounts["teacher"]
    lesson = learning.save_lesson(db_session, teacher, module.id, {"title": "Quiz", "kind": "quiz"})
    question = learning.save_quiz_question(
        db_session,
        teacher,
        lesson.id,
        {"prompt": "Which answer?", "options": ["First", "Second"], "correct_index": 0},
    )
    learning.set_course_status(db_session, teacher, course.id, "published")
    original_revision = lesson.revision
    learning.delete_learning_item(db_session, teacher, "question", question.id)
    assert lesson.revision == original_revision + 1
    assert course.status == "draft"


def test_lesson_content_revisions_change_only_when_learning_definition_changes(
    db_session, education_accounts, education_course
):
    _, module, lesson = education_course
    teacher = education_accounts["teacher"]
    initial = lesson.revision
    learning.save_lesson(
        db_session,
        teacher,
        module.id,
        {"title": "Renamed lesson", "kind": "text", "content": lesson.content},
        lesson_id=lesson.id,
    )
    assert lesson.revision == initial
    learning.save_lesson(
        db_session,
        teacher,
        module.id,
        {"title": lesson.title, "kind": "text", "content": "New teaching material."},
        lesson_id=lesson.id,
    )
    assert lesson.revision == initial + 1
