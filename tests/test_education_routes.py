"""Real learning HTTP journeys with isolated accounts and mocked media transport.

These checks exercise signed sessions, CSRF, templates and domain persistence
together. Synthetic provider grants/callbacks never contact a LiveKit project or
private recording storage, and no test modifies an operator's database.
"""

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.education import (
    EducatorProfile,
    LearningAttendance,
    LearningCourse,
    LearningEnrollment,
    LearningLesson,
    LearningModule,
    LearningRecording,
    LearningWebhookReceipt,
    LessonProgress,
    QuizAttempt,
    SessionMessage,
    SessionRegistration,
)
from app.services import education, education_live
from app.services.auth import register_user
from tests.helpers import csrf_from
from tests.test_community import sign_in

PREFIX = "/learning/live"
JSON_HEADERS = {"Accept": "application/json"}


@pytest.fixture
def learning_accounts(db_session):
    accounts = {}
    for number, name in enumerate(("teacher", "student", "other", "staff"), 1):
        user = register_user(db_session, phone=f"+234800010000{number}", password="s3cret-pass")
        user.full_name = f"Private {name} identity"
        user.is_staff = name == "staff"
        accounts[name] = user
    db_session.commit()
    return accounts


def application_data():
    return {
        "display_name": "Public educator",
        "headline": "Nursing communication educator",
        "bio": "Practical teaching and learner support.",
        "subjects": "Communication, leadership",
    }


def course_data():
    return {
        "title": "Learning to communicate",
        "summary": "Build clear and respectful communication.",
        "description": "Reading, practice and a knowledge check.",
        "category": "Communication",
        "level": "beginner",
    }


def session_data(**extra):
    starts = datetime.now(UTC) - timedelta(minutes=2)
    return {
        "title": "Communication live lecture",
        "description": "Discuss clear communication with colleagues.",
        "objectives": "Ask questions and practice listening.",
        "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=1)).isoformat(),
        "timezone": "Africa/Lagos",
        "capacity": "2",
        "status": "scheduled",
        "session_format": "lecture",
        "chat_enabled": "true",
        **extra,
    }


def signed_in(client, account):
    sign_in(client, account.phone)
    return csrf_from(client.get(PREFIX + "/studio"))


def post(client, path, token, **values):
    return client.post(path, data={"csrf_token": token, **values}, follow_redirects=False)


def hidden(response, name):
    match = re.search(r'name="' + name + r'"\s+value="([^"]+)"', response.text)
    assert match is not None, f"missing {name} in form"
    return match.group(1)


@pytest.fixture
def learning_course(db_session, learning_accounts):
    teacher = learning_accounts["teacher"]
    education.apply_educator(db_session, teacher, application_data())
    education.review_educator(db_session, learning_accounts["staff"], teacher.id, "approved")
    course = education.create_course(db_session, teacher, course_data())
    module = education.save_module(db_session, teacher, course.id, {"title": "First steps"})
    lesson = education.save_lesson(
        db_session,
        teacher,
        module.id,
        {"title": "Listen carefully", "kind": "text", "content": "Private lesson content."},
    )
    quiz = education.save_lesson(
        db_session, teacher, module.id, {"title": "Check understanding", "kind": "quiz"}
    )
    question = education.save_quiz_question(
        db_session,
        teacher,
        quiz.id,
        {
            "prompt": "Which response helps communication?",
            "options": ["Listen first", "Interrupt"],
            "correct_index": "0",
            "explanation": "Listening helps us understand another perspective.",
        },
    )
    education.set_course_status(db_session, teacher, course.id, "published")
    return course, module, lesson, quiz, question


@pytest.fixture
def learning_session(db_session, learning_accounts, learning_course):
    course, _, _, _, _ = learning_course
    session = education.create_session(
        db_session,
        learning_accounts["teacher"],
        session_data(course_id=str(course.id), recording_enabled="true"),
    )
    education.enroll(db_session, learning_accounts["student"], course.id)
    education.register_session(db_session, learning_accounts["student"], session.id)
    return session


@pytest.fixture
def synthetic_provider(monkeypatch):
    """Only local JWT/S3 signing is enabled; every remote operation is mocked."""
    values = {
        "livekit_url": "wss://classrooms.example.com",
        "livekit_api_key": "route-synthetic-key",
        "livekit_api_secret": "route-synthetic-secret" * 2,
        "learning_recording_s3_bucket": "private-route-recordings",
        "learning_recording_s3_region": "eu-west-1",
        "learning_recording_s3_access_key": "synthetic-storage-key",
        "learning_recording_s3_secret_key": "synthetic-storage-secret",
        "learning_recording_s3_endpoint": "https://storage.example.com",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    return values


def test_application_review_course_authoring_and_learner_progress(
    client, db_session, learning_accounts
):
    teacher, student, staff = (learning_accounts[name] for name in ("teacher", "student", "staff"))
    token = signed_in(client, teacher)
    assert post(client, PREFIX + "/educator", token, **application_data()).status_code == 303
    assert db_session.get(EducatorProfile, teacher.id).status == "pending"
    assert not teacher.is_staff
    assert post(client, PREFIX + "/courses", token, **course_data()).status_code == 403
    assert client.get("/staff/educators").status_code == 403

    token = signed_in(client, staff)
    assert "Public educator" in client.get("/staff/educators?status=pending").text
    response = post(
        client, f"/staff/educators/{teacher.id}/review", token, status="approved", notes="Approved"
    )
    assert response.status_code == 303
    assert db_session.get(EducatorProfile, teacher.id).status == "approved"
    assert "Public educator" in client.get("/staff/educators?status=approved").text
    assert not teacher.is_staff

    token = signed_in(client, teacher)
    assert post(client, PREFIX + "/courses", token, **course_data()).status_code == 303
    course = db_session.scalar(select(LearningCourse))
    course_path = f"{PREFIX}/courses/{course.id}"
    assert client.get(course_path).status_code == 200
    assert post(client, course_path + "/modules", token, title="First steps").status_code == 303
    module = db_session.scalar(select(LearningModule))
    assert (
        post(
            client,
            f"{PREFIX}/modules/{module.id}/lessons",
            token,
            title="Listen carefully",
            kind="text",
            content="Private lesson content.",
        ).status_code
        == 303
    )
    lesson = db_session.scalar(select(LearningLesson))
    assert post(client, course_path + "/status", token, status="published").status_code == 303

    client.cookies.clear()
    outline = client.get(course_path)
    assert outline.status_code == 200
    assert lesson.title in outline.text
    assert lesson.content not in outline.text
    assert teacher.full_name not in outline.text
    assert teacher.phone not in outline.text
    assert course.title in client.get(PREFIX).text

    token = signed_in(client, student)
    lesson_path = f"{PREFIX}/lessons/{lesson.id}"
    assert client.get(lesson_path).status_code == 403
    for _ in range(2):
        assert (
            post(client, course_path + "/enroll", token, user_id=str(staff.id)).status_code == 303
        )
    assert db_session.scalar(select(func.count()).select_from(LearningEnrollment)) == 1
    assert db_session.get(LearningEnrollment, (course.id, staff.id)) is None
    assert lesson.content in client.get(lesson_path).text
    for _ in range(2):
        assert post(client, lesson_path + "/complete", token).status_code == 303
    assert db_session.scalar(select(func.count()).select_from(LessonProgress)) == 1
    assert "100%" in client.get(course_path).text
    assert course.title in client.get(PREFIX + "/mine").text


def test_draft_and_authoring_permissions_with_retained_invalid_input(
    client, db_session, learning_accounts, learning_course
):
    course, module, lesson, _, _ = learning_course
    teacher = learning_accounts["teacher"]
    education.set_course_status(db_session, teacher, course.id, "draft")
    path = f"{PREFIX}/courses/{course.id}"
    client.cookies.clear()
    assert client.get(path).status_code == 404
    assert course.title not in client.get(PREFIX).text
    token = signed_in(client, learning_accounts["other"])
    assert client.get(path).status_code == 404
    assert post(client, path + "/status", token, status="published").status_code == 403
    education.set_course_status(db_session, teacher, course.id, "published")
    assert client.get(path + "/edit").status_code == 403
    assert client.get(f"{PREFIX}/modules/{module.id}/edit").status_code == 403
    assert client.get(f"{PREFIX}/lessons/{lesson.id}/edit").status_code == 403

    token = signed_in(client, teacher)
    response = post(
        client,
        f"{PREFIX}/modules/{module.id}/lessons",
        token,
        title="Keep my lesson title",
        kind="resource",
        resource_url="javascript:alert(1)",
    )
    assert response.status_code == 400
    assert "Keep my lesson title" in response.text
    assert "public HTTPS" in response.text
    assert db_session.scalar(select(func.count()).select_from(LearningLesson)) == 2
    assert post(client, path + "/edit", "bad-token", **course_data()).status_code == 400


@pytest.mark.parametrize("decision", ["paused", "rejected"])
def test_staff_revocation_closes_media_before_changing_educator_approval(
    decision, client, db_session, learning_accounts, learning_session, monkeypatch
):
    session = learning_session
    teacher = learning_accounts["teacher"]
    education.change_session_state(db_session, teacher, session.id, "live")
    closed = []

    def close(room_id):
        assert db_session.get(EducatorProfile, teacher.id).status == "approved"
        assert session.status == "live"
        closed.append(room_id)

    monkeypatch.setattr(education_live, "delete_room", close)
    token = signed_in(client, learning_accounts["staff"])
    path = f"/staff/educators/{teacher.id}/review"
    for invalid in ({"status": "unknown"}, {"status": decision, "notes": "x" * 2001}):
        assert post(client, path, token, **invalid).status_code == 400
    assert closed == []
    assert post(client, path, token, status=decision).status_code == 303
    assert closed == [session.id]
    db_session.refresh(session)
    assert session.status == "ended"
    assert db_session.get(EducatorProfile, teacher.id).status == decision
    assert post(client, path, token, status=decision).status_code == 303
    assert closed == [session.id]
    signed_in(client, learning_accounts["student"])
    assert client.get(f"{PREFIX}/sessions/{session.id}/room").status_code == 404


def test_failed_revocation_rolls_back_approval_and_retries_partial_remote_closure(
    client, db_session, learning_accounts, learning_session, monkeypatch
):
    teacher = learning_accounts["teacher"]
    first = learning_session
    second = education.create_session(db_session, teacher, session_data(title="Second classroom"))
    for session in (first, second):
        education.change_session_state(db_session, teacher, session.id, "live")
    sessions = sorted((first, second), key=lambda session: session.id)
    remote_closed = set()
    calls = []

    def close(room_id):
        calls.append(room_id)
        if len(calls) == 2:
            raise education_live.EducationLiveError("The classroom service is unavailable.")
        # A repeated delete of the first room is intentionally harmless.
        remote_closed.add(room_id)

    monkeypatch.setattr(education_live, "delete_room", close)
    token = signed_in(client, learning_accounts["staff"])
    path = f"/staff/educators/{teacher.id}/review"
    result = client.post(path, data={"csrf_token": token, "status": "paused"}, headers=JSON_HEADERS)
    assert result.status_code == 503
    assert db_session.get(EducatorProfile, teacher.id).status == "approved"
    for session in sessions:
        db_session.refresh(session)
        assert session.status == "live"
    assert remote_closed == {sessions[0].id}
    assert post(client, path, token, status="paused").status_code == 303
    assert db_session.get(EducatorProfile, teacher.id).status == "paused"
    assert remote_closed == {first.id, second.id}
    assert calls == [sessions[0].id, sessions[1].id, sessions[0].id, sessions[1].id]
    for session in sessions:
        db_session.refresh(session)
        assert session.status == "ended"


def test_changed_approved_identity_requires_media_closure_before_reapplication(
    client, db_session, learning_accounts, learning_session, monkeypatch
):
    session = learning_session
    teacher = learning_accounts["teacher"]
    education.change_session_state(db_session, teacher, session.id, "live")
    closed = []

    def close(room_id):
        assert db_session.get(EducatorProfile, teacher.id).status == "approved"
        closed.append(room_id)

    monkeypatch.setattr(education_live, "delete_room", close)
    token = signed_in(client, teacher)
    path = PREFIX + "/educator"
    assert post(client, path, token, **application_data()).status_code == 303
    assert closed == []
    assert db_session.get(EducatorProfile, teacher.id).status == "approved"
    assert post(client, path, token, **{**application_data(), "bio": ""}).status_code == 400
    assert closed == []

    def unavailable(*args, **kwargs):
        raise education_live.EducationLiveError("The classroom service is unavailable.")

    monkeypatch.setattr(education_live, "delete_room", unavailable)
    changed = {**application_data(), "display_name": "New educator identity"}
    result = client.post(path, data={"csrf_token": token, **changed}, headers=JSON_HEADERS)
    assert result.status_code == 503
    assert db_session.get(EducatorProfile, teacher.id).status == "approved"
    assert db_session.get(EducatorProfile, teacher.id).display_name == "Public educator"
    db_session.refresh(session)
    assert session.status == "live"

    monkeypatch.setattr(education_live, "delete_room", close)
    assert post(client, path, token, **changed).status_code == 303
    assert closed == [session.id]
    db_session.refresh(session)
    assert session.status == "ended"
    assert db_session.get(EducatorProfile, teacher.id).status == "pending"
    assert db_session.get(EducatorProfile, teacher.id).display_name == changed["display_name"]


def test_quiz_http_revision_retries_and_private_answer_keys(
    client, db_session, learning_accounts, learning_course
):
    course, _, _, quiz, question = learning_course
    student, teacher = learning_accounts["student"], learning_accounts["teacher"]
    education.enroll(db_session, student, course.id)
    token = signed_in(client, student)
    path = f"{PREFIX}/lessons/{quiz.id}"
    form = client.get(path)
    assert form.status_code == 200
    assert 'name="correct_index"' not in form.text
    assert question.explanation not in form.text
    values = {
        "request_id": hidden(form, "request_id"),
        "lesson_revision": hidden(form, "lesson_revision"),
        f"question_{question.id}": "0",
    }
    assert post(client, path + "/complete", token).status_code == 400
    for _ in range(2):
        assert post(client, path + "/quiz", token, **values).status_code == 303
    assert db_session.scalar(select(func.count()).select_from(QuizAttempt)) == 1
    assert "100% correct" in client.get(path).text
    assert question.explanation in client.get(path).text

    education.save_quiz_question(
        db_session,
        teacher,
        quiz.id,
        {
            "prompt": question.prompt,
            "options": question.options,
            "correct_index": "1",
            "explanation": "Revised teaching explanation.",
            "position": question.position,
        },
        question_id=question.id,
    )
    assert post(client, path + "/quiz", token, **values).status_code == 409
    assert db_session.scalar(select(func.count()).select_from(QuizAttempt)) == 1
    assert "100% correct" not in client.get(path).text
    assert db_session.get(LessonProgress, (quiz.id, student.id)) is None
    current_values = {**values, "request_id": str(uuid4())}
    current_values.pop("lesson_revision")
    assert post(client, path + "/quiz", token, **current_values).status_code == 400


def test_anonymous_learning_actions_require_sign_in(client, learning_course):
    course, _, lesson, _, _ = learning_course
    for path in (PREFIX + "/mine", PREFIX + "/studio", f"{PREFIX}/lessons/{lesson.id}"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"
    assert client.get(f"{PREFIX}/courses/{course.id}").status_code == 200


def test_session_schedule_reservation_course_gate_and_calendar(
    client, db_session, learning_accounts, learning_course
):
    course, _, _, _, _ = learning_course
    token = signed_in(client, learning_accounts["teacher"])
    response = post(client, PREFIX + "/sessions", token, **session_data(course_id=str(course.id)))
    assert response.status_code == 303
    from app.models.education import LearningSession

    session = db_session.scalar(select(LearningSession))
    path = f"{PREFIX}/sessions/{session.id}"
    token = signed_in(client, learning_accounts["student"])
    assert post(client, path + "/register", token).status_code == 403
    education.enroll(db_session, learning_accounts["student"], course.id)
    for _ in range(2):
        assert post(client, path + "/register", token).status_code == 303
    db_session.refresh(session)
    assert session.reserved_count == 1
    assert db_session.scalar(select(func.count()).select_from(SessionRegistration)) == 1
    assert client.get(path + "/room").status_code == 200
    calendar = client.get(path + "/calendar.ics")
    assert calendar.status_code == 200
    assert "BEGIN:VEVENT" in calendar.text
    assert "Nurse.ng online classroom" in calendar.text
    assert learning_accounts["student"].phone not in calendar.text
    for _ in range(2):
        assert post(client, path + "/withdraw", token).status_code == 303
    db_session.refresh(session)
    assert session.reserved_count == 0
    assert client.get(path + "/room").status_code == 403


def test_missing_media_keeps_schedule_and_attendance_honest(
    client, db_session, learning_accounts, learning_session, monkeypatch
):
    for field in ("livekit_url", "livekit_api_key", "livekit_api_secret"):
        monkeypatch.setattr(settings, field, "")
    session = learning_session
    token = signed_in(client, learning_accounts["teacher"])
    path = f"{PREFIX}/sessions/{session.id}"
    response = client.post(path + "/start", data={"csrf_token": token}, headers=JSON_HEADERS)
    assert response.status_code == 503
    db_session.refresh(session)
    assert session.status == "scheduled"
    assert db_session.scalar(select(func.count()).select_from(LearningAttendance)) == 0
    assert "not available" in client.get(PREFIX).text


@pytest.mark.parametrize("restriction", ["educator_paused", "course_withdrawn"])
def test_invalid_start_is_rejected_before_a_remote_room_is_created(
    restriction, client, db_session, learning_accounts, learning_session, monkeypatch
):
    session = learning_session
    if restriction == "educator_paused":
        education.review_educator(
            db_session, learning_accounts["staff"], session.educator_id, "paused"
        )
    else:
        education.set_course_status(
            db_session, learning_accounts["teacher"], session.course_id, "draft"
        )

    def should_not_create(*args, **kwargs):
        pytest.fail("Invalid session authorization reached the remote media provider")

    monkeypatch.setattr(education_live, "create_room", should_not_create)
    token = signed_in(client, learning_accounts["staff"])
    response = client.post(
        f"{PREFIX}/sessions/{session.id}/start",
        data={"csrf_token": token},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 400
    db_session.refresh(session)
    assert session.status == "scheduled"


def test_classroom_lifecycle_grants_consent_and_persistent_moderation(
    client, db_session, learning_accounts, learning_session, synthetic_provider, monkeypatch
):
    session = learning_session
    path = f"{PREFIX}/sessions/{session.id}"
    provider_calls = []
    monkeypatch.setattr(
        education_live,
        "create_room",
        lambda room, **kwargs: provider_calls.append(("create", room)),
    )
    monkeypatch.setattr(
        education_live, "delete_room", lambda room: provider_calls.append(("delete", room))
    )
    monkeypatch.setattr(
        education_live,
        "moderate_participant",
        lambda room, target, **kwargs: provider_calls.append((kwargs["action"], room, target)),
    )
    student = learning_accounts["student"]
    token = signed_in(client, student)
    assert post(client, path + "/start", token).status_code == 403
    token = signed_in(client, learning_accounts["teacher"])
    assert post(client, path + "/start", token).status_code == 303
    db_session.refresh(session)
    assert session.status == "live"
    assert provider_calls == [("create", session.id)]

    token = signed_in(client, student)
    headers = {**JSON_HEADERS, "X-CSRF-Token": token}
    assert client.post(path + "/token", json={}, headers=headers).status_code == 400
    response = client.post(
        path + "/token", json={"recording_consent": True, "is_host": True}, headers=headers
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    grant = jwt.decode(
        response.json()["token"],
        synthetic_provider["livekit_api_secret"],
        algorithms=["HS256"],
        issuer=synthetic_provider["livekit_api_key"],
    )
    assert grant["video"]["room"] == education_live.room_name(session.id)
    assert grant["video"]["canPublish"] is False
    assert not grant["video"].get("roomAdmin", False)
    assert grant["name"] == "Learner"
    assert db_session.scalar(select(func.count()).select_from(LearningAttendance)) == 0
    assert client.post(path + "/hand", json={"raised": True}, headers=headers).status_code == 200
    assert (
        client.post(
            path + "/moderation",
            json={"action": "allow_speaking", "identity": str(student.id)},
            headers=headers,
        ).status_code
        == 403
    )

    token = signed_in(client, learning_accounts["teacher"])
    headers = {**JSON_HEADERS, "X-CSRF-Token": token}
    assert (
        client.post(
            path + "/moderation",
            json={"action": "allow_speaking", "identity": str(student.id)},
            headers=headers,
        ).status_code
        == 200
    )
    registration = db_session.get(SessionRegistration, (session.id, student.id))
    assert registration.speaker_allowed is True
    assert registration.hand_raised_at is None
    assert (
        client.post(
            path + "/moderation",
            json={"action": "remove", "identity": str(student.id)},
            headers=headers,
        ).status_code
        == 200
    )
    assert db_session.get(SessionRegistration, (session.id, student.id)).status == "removed"
    token = signed_in(client, student)
    assert (
        client.post(
            path + "/token",
            json={"recording_consent": True},
            headers={**JSON_HEADERS, "X-CSRF-Token": token},
        ).status_code
        == 403
    )

    token = signed_in(client, learning_accounts["teacher"])
    assert post(client, path + "/end", token).status_code == 303
    db_session.refresh(session)
    assert session.status == "ended"
    assert provider_calls[-1] == ("delete", session.id)


def test_classroom_json_csrf_bounds_and_type_errors_are_safe(
    client, db_session, learning_accounts, learning_session
):
    session = learning_session
    education.change_session_state(db_session, learning_accounts["teacher"], session.id, "live")
    token = signed_in(client, learning_accounts["student"])
    path = f"{PREFIX}/sessions/{session.id}"
    headers = {**JSON_HEADERS, "X-CSRF-Token": token}
    assert client.post(path + "/messages", json={"body": "Question"}).status_code == 400
    for payload in ([], {"body": []}, {"body": "Question", "kind": []}):
        assert client.post(path + "/messages", json=payload, headers=headers).status_code == 400
    assert client.post(path + "/messages", content="{", headers=headers).status_code == 400
    assert client.post(path + "/messages", content="x" * 17000, headers=headers).status_code == 413
    assert client.post(path + "/hand", json={"raised": "true"}, headers=headers).status_code == 400
    assert (
        client.post(
            path + "/messages",
            json={"body": "Question"},
            headers={"X-CSRF-Token": b"\xff", **JSON_HEADERS},
        ).status_code
        == 400
    )
    assert db_session.scalar(select(func.count()).select_from(SessionMessage)) == 0

    token = signed_in(client, learning_accounts["teacher"])
    headers = {**JSON_HEADERS, "X-CSRF-Token": token}
    for payload in ({"action": []}, {"action": "answer", "answer": []}):
        assert client.post(path + "/moderation", json=payload, headers=headers).status_code == 400


def test_private_questions_state_and_provider_failure_do_not_remove_access(
    client, db_session, learning_accounts, learning_session, monkeypatch
):
    session = learning_session
    education.change_session_state(db_session, learning_accounts["teacher"], session.id, "live")
    student = learning_accounts["student"]
    token = signed_in(client, student)
    path = f"{PREFIX}/sessions/{session.id}"
    response = client.post(
        path + "/messages",
        json={"body": "How can I listen well?"},
        headers={**JSON_HEADERS, "X-CSRF-Token": token},
    )
    assert response.status_code == 201
    state = client.get(path + "/room-state").json()
    assert state["participants"] == []
    assert state["messages"][0]["body"] == "How can I listen well?"
    assert student.full_name not in json.dumps(state)
    assert student.phone not in json.dumps(state)
    signed_in(client, learning_accounts["other"])
    assert client.get(path + "/room-state").status_code == 403
    token = signed_in(client, learning_accounts["teacher"])

    def unavailable(*args, **kwargs):
        raise education_live.EducationLiveError("The classroom service is unavailable.")

    monkeypatch.setattr(education_live, "moderate_participant", unavailable)
    response = client.post(
        path + "/moderation",
        json={"action": "remove", "identity": str(student.id)},
        headers={**JSON_HEADERS, "X-CSRF-Token": token},
    )
    assert response.status_code == 503
    assert db_session.get(SessionRegistration, (session.id, student.id)).status == "reserved"
    response = client.post(
        path + "/moderation",
        json={"action": "answer", "message_id": response_id(db_session), "answer": "Pause first."},
        headers={**JSON_HEADERS, "X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert db_session.scalar(select(SessionMessage)).answer == "Pause first."


def response_id(db):
    return str(db.scalar(select(SessionMessage.id)))


def signed_webhook(event, provider):
    body = json.dumps(event, separators=(",", ":")).encode()
    token = jwt.encode(
        {
            "iss": provider["livekit_api_key"],
            "exp": datetime.now(UTC) + timedelta(minutes=1),
            "sha256": base64.b64encode(hashlib.sha256(body).digest()).decode(),
        },
        provider["livekit_api_secret"],
        algorithm="HS256",
    )
    return body, {"Authorization": "Bearer " + token, **JSON_HEADERS}


def test_signed_callback_establishes_attendance_and_rejects_tampering(
    client, db_session, learning_accounts, learning_session, synthetic_provider
):
    session = learning_session
    student = learning_accounts["student"]
    event = {
        "id": "http-signed-join",
        "event": "participant_joined",
        "createdAt": int(datetime.now(UTC).timestamp()),
        "room": {"name": education_live.room_name(session.id)},
        "participant": {"identity": str(student.id), "sid": "synthetic-participant"},
    }
    body, headers = signed_webhook(event, synthetic_provider)
    path = PREFIX + "/webhooks/livekit"
    assert client.post(path, content=body).status_code == 401
    assert client.post(path, content=body + b" ", headers=headers).status_code == 401
    assert db_session.scalar(select(func.count()).select_from(LearningAttendance)) == 0
    for _ in range(2):
        assert client.post(path, content=body, headers=headers).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(LearningAttendance)) == 1
    assert db_session.scalar(select(func.count()).select_from(LearningWebhookReceipt)) == 1
    signed_in(client, student)
    state = client.get(f"{PREFIX}/sessions/{session.id}/room-state").json()
    assert state["participants"][0]["display_name"] == "Learner"
    assert student.full_name not in json.dumps(state)
    assert student.phone not in json.dumps(state)
    staff = learning_accounts["staff"]
    body, headers = signed_webhook(
        {
            **event,
            "id": "http-signed-moderator-join",
            "participant": {"identity": str(staff.id), "sid": "synthetic-moderator"},
        },
        synthetic_provider,
    )
    assert client.post(path, content=body, headers=headers).status_code == 200
    state = client.get(f"{PREFIX}/sessions/{session.id}/room-state").json()
    moderator = next(row for row in state["participants"] if row["identity"] == str(staff.id))
    assert moderator["display_name"] == "Moderator"
    assert moderator["is_host"] is True
    assert staff.full_name not in json.dumps(state)


def test_recording_request_and_private_playback_recheck_reservations(
    client, db_session, learning_accounts, learning_session, synthetic_provider, monkeypatch
):
    session = learning_session
    teacher = learning_accounts["teacher"]
    education.change_session_state(db_session, teacher, session.id, "live")
    key = f"learning/{session.id}/lecture.mp4"
    monkeypatch.setattr(
        education_live,
        "start_recording",
        lambda _: {"egress_id": "synthetic-egress", "object_key": key},
    )
    token = signed_in(client, teacher)
    path = f"{PREFIX}/sessions/{session.id}"
    assert post(client, path + "/recording", token, action="bad").status_code == 400
    for _ in range(2):
        assert post(client, path + "/recording", token, action="start").status_code == 303
    recording = db_session.scalar(select(LearningRecording))
    assert recording.status == "starting"
    assert db_session.scalar(select(func.count()).select_from(LearningRecording)) == 1
    playback = f"{PREFIX}/recordings/{recording.id}"
    assert client.get(playback, follow_redirects=False).status_code == 404
    event = {
        "id": "http-egress-complete",
        "event": "egress_ended",
        "createdAt": int(datetime.now(UTC).timestamp()),
        "room": {"name": education_live.room_name(session.id)},
        "egressInfo": {
            "egressId": "synthetic-egress",
            "status": "EGRESS_COMPLETE",
            "fileResults": [{"filename": key, "size": 1024}],
        },
    }
    body, headers = signed_webhook(event, synthetic_provider)
    assert (
        client.post(PREFIX + "/webhooks/livekit", content=body, headers=headers).status_code == 200
    )
    db_session.refresh(recording)
    assert recording.status == "complete"
    token = signed_in(client, learning_accounts["student"])
    response = client.get(playback, follow_redirects=False)
    assert response.status_code == 303
    assert "X-Amz-Signature=" in response.headers["location"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert post(client, path + "/withdraw", token).status_code == 303
    assert client.get(playback, follow_redirects=False).status_code == 403
    signed_in(client, learning_accounts["other"])
    assert client.get(playback, follow_redirects=False).status_code == 403
