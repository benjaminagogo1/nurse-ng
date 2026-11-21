"""Shared presentation helpers for learning pages and classroom endpoints.

Domain services authorize access before these helpers build template context.
The dictionaries here describe the current database state; they do not grant
permissions, infer attendance from a reservation, or expose quiz answer keys.
Keeping presentation queries here lets route handlers focus on HTTP behavior.
See docs/LIVE_LEARNING_ARCHITECTURE.md for the end-to-end request flows.
"""

from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select

from app.models.education import (
    EducatorProfile,
    LearningEnrollment,
    LearningLesson,
    LearningModule,
    LearningSession,
    LessonProgress,
    SessionRegistration,
)
from app.services import education, education_live
from app.services.events import local_time
from app.web.templating import render

PREFIX = "/learning/live"


def learning_page(request, template, user=None, **context):
    """Render a learning template with capability presence, never provider secrets."""
    capabilities = education_live.provider_status()
    return render(
        request,
        "education/" + template + ".html",
        {
            "user": user,
            "title": "Learning and live lectures",
            "values": {},
            "live_available": capabilities["configured"],
            "recording_available": capabilities["recording_configured"],
            "local_time": local_time,
            "education_page": "catalog"
            if template in {"catalog", "course", "lesson", "session", "room"}
            else "mine"
            if template == "mine"
            else "review"
            if template == "educator_review"
            else "studio",
            **context,
        },
    )


def teaching_profile(db, user):
    """Return only the signed-in member's own educator application, if any."""
    return db.get(EducatorProfile, user.id) if user else None


def manages(db, user, educator_id):
    """UI hint matching the domain's educator ownership or staff review boundary."""
    return bool(
        user and (user.is_staff or (user.id == educator_id and education.can_teach(db, user)))
    )


def course_context(db, course, user):
    """Build an ordered outline and learner progress after course authorization.

    Completion is calculated from the current outline so adding a lesson cannot
    leave a misleading 100% indicator. Progress rows are scoped to this user.
    Lesson content is rendered only by the authorized lesson reader.
    """
    modules = list(
        db.scalars(
            select(LearningModule)
            .where(
                LearningModule.course_id == course.id,
            )
            .order_by(LearningModule.position)
        )
    )
    module_ids = [module.id for module in modules]
    lessons = (
        list(
            db.scalars(
                select(LearningLesson)
                .where(
                    LearningLesson.module_id.in_(module_ids),
                )
                .order_by(LearningLesson.position)
            )
        )
        if module_ids
        else []
    )
    by_module = {module.id: [] for module in modules}
    for lesson in lessons:
        by_module[lesson.module_id].append(lesson)
    ordered = [lesson for module in modules for lesson in by_module[module.id]]
    completed = (
        set(
            db.scalars(
                select(LessonProgress.lesson_id).where(
                    LessonProgress.user_id == user.id,
                    LessonProgress.lesson_id.in_([lesson.id for lesson in ordered]),
                )
            )
        )
        if user and ordered
        else set()
    )
    total = len(ordered)
    enrollment = db.get(LearningEnrollment, (course.id, user.id)) if user else None
    sessions = list(
        db.scalars(
            select(LearningSession)
            .where(
                LearningSession.course_id == course.id,
                LearningSession.status.in_(["scheduled", "live"]),
            )
            .order_by(LearningSession.starts_at)
        )
    )
    return {
        "course": course,
        "modules": modules,
        "lessons_by_module": by_module,
        "ordered_lessons": ordered,
        "completed_lesson_ids": completed,
        "enrollment": enrollment,
        "can_manage": manages(db, user, course.educator_id),
        "progress": {
            "percent": len(completed) * 100 // total if total else 0,
            "completed": len(completed),
            "total": total,
        },
        "next_lesson": next((item for item in ordered if item.id not in completed), None),
        "sessions": sessions,
    }


def managed_course(db, user, course_id):
    """Authorize the authoring view without allowing another educator's drafts."""
    course = education.get_course(db, course_id, user=user)
    if not manages(db, user, course.educator_id):
        raise HTTPException(403, "Only this course's educator can manage it.")
    return course


def managed_module(db, user, module_id):
    """Resolve a module through its owning course before showing an edit form."""
    module = db.get(LearningModule, module_id)
    if module is None:
        raise HTTPException(404, "This course module is unavailable.")
    return module, managed_course(db, user, module.course_id)


def lesson_context(db, user, lesson_id):
    """Require enrollment or author access before returning teaching content."""
    lesson = db.get(LearningLesson, lesson_id)
    if lesson is None:
        raise HTTPException(404, "This lesson is unavailable.")
    module = db.get(LearningModule, lesson.module_id)
    course = education.get_course(db, module.course_id, user=user)
    context = course_context(db, course, user)
    if not context["enrollment"] and not context["can_manage"]:
        raise HTTPException(403, "Enroll in this course to open its lessons.")
    ordered = context["ordered_lessons"]
    index = next(index for index, item in enumerate(ordered) if item.id == lesson.id)
    return {
        **context,
        "lesson": lesson,
        "module": module,
        "lesson_completed": lesson.id in context["completed_lesson_ids"],
        "previous_lesson": ordered[index - 1] if index else None,
        "next_lesson": ordered[index + 1] if index + 1 < len(ordered) else None,
        "quiz_questions": education.quiz_questions(db, user, lesson.id)
        if lesson.kind == "quiz"
        else [],
    }


def session_context(db, session, user):
    """Keep public session details separate from private learner reservations."""
    registration = db.get(SessionRegistration, (session.id, user.id)) if user else None
    can_manage = manages(db, user, session.educator_id)
    return {
        "session": session,
        "course": session.course,
        "educator": session.educator,
        "registration": registration
        if registration and registration.status == "reserved"
        else None,
        "can_manage": can_manage,
        "can_join": session.status == "live"
        and bool(can_manage or (registration and registration.status == "reserved")),
        "can_start": session.status == "scheduled"
        and education.utc(session.starts_at) - timedelta(minutes=15)
        <= datetime.now(UTC)
        < education.utc(session.ends_at),
        "course_enrollment": bool(
            user
            and (
                not session.course_id
                or db.get(LearningEnrollment, (session.course_id, user.id))
                or can_manage
            )
        ),
    }


def form_values(record, fields):
    """Copy only editable fields; secrets and review history are never form data."""
    values = {field: getattr(record, field) for field in fields}
    if isinstance(record, LearningSession):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(record.timezone)
        for field in ("starts_at", "ends_at"):
            value = values[field]
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            values[field] = value.astimezone(zone).strftime("%Y-%m-%dT%H:%M")
        values["course_id"] = str(record.course_id) if record.course_id else ""
    return values


async def classroom_json(request: Request):
    """Bound JSON mutations and verify the session's CSRF header.

    The signed provider webhook intentionally uses another path and does not
    use this browser-session helper. A valid JSON body alone is never authority.
    """
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token", "")
    if (
        not isinstance(expected, str)
        or not supplied
        or not compare_digest(expected.encode(), supplied.encode())
    ):
        raise HTTPException(400, "Refresh the page before trying this classroom action.")
    raw = await bounded_body(request, 16_384)
    import json

    try:
        payload = json.loads(raw or b"{}")
    except (ValueError, UnicodeError):
        raise HTTPException(400, "This classroom request is invalid.") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "This classroom request is invalid.")
    return payload


async def bounded_body(request: Request, maximum: int):
    """Bound streamed/chunked input before retaining bytes or parsing JSON.

    Checking the length after request.body() would already have allocated an
    attacker-controlled body. Content-Length is an early hint; the stream count
    remains authoritative when the header is absent or inaccurate.
    """
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) < 0:
                raise ValueError
            if int(length) > maximum:
                raise HTTPException(413, "This classroom request is too large.")
        except ValueError:
            raise HTTPException(400, "This classroom request is invalid.") from None
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > maximum:
            raise HTTPException(413, "This classroom request is too large.")
        buffer.extend(chunk)
    return bytes(buffer)


def identifier(value):
    """Normalize user-supplied UUIDs to a safe 400 response, never a server error."""
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Choose a valid classroom item.") from None
