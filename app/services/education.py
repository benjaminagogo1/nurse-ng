"""Education authorization, content editing, progress and live-session lifecycle.

Public services validate member identity and ownership before changing records.
Educator approval is independent of staff access. Courses stay private until
explicitly published with usable lessons; answer keys stay server-side. A seat
reservation is allocated with a conditional database UPDATE, not a count followed
by an insert, which prevents oversubscription when requests race.

``handle_live_webhook`` is an internal boundary: callers MUST authenticate the
provider's signature first. Only that boundary creates attendance/recordings.
Provider retries are deduplicated by a receipt in the same transaction. Client
claims of attendance, quiz scores or room permissions are never accepted.

Mutating public functions commit their transaction. Expected validation and
authorization failures raise EducationError; callers should roll back before
rendering their form errors. URLs are external resources, never fetched or stored
as uploads by this module. Completion is learning progress, not accreditation.
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.models.education import (
    EducatorProfile,
    EducatorReview,
    LearningAttendance,
    LearningCourse,
    LearningEnrollment,
    LearningLesson,
    LearningModule,
    LearningRecording,
    LearningSession,
    LearningWebhookReceipt,
    LessonProgress,
    QuizAttempt,
    QuizQuestion,
    SessionMessage,
    SessionModeration,
    SessionRegistration,
)
from app.models.user import User, UserStatus

COURSE_LEVELS = {"beginner", "intermediate", "advanced", "all"}
LESSON_KINDS = {"text", "resource", "video", "quiz"}
SESSION_FORMATS = {"lecture", "discussion"}


class EducationError(ValueError):
    """A safe user-facing error with an appropriate HTTP status for route adapters."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def utc(value):
    """Normalize SQLite's naive timestamps and provider timestamps to UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _identifier(value):
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError):
        raise EducationError("This learning item is unavailable.", 404) from None


def _active(user):
    if user is None or not user.is_active or user.status != UserStatus.ACTIVE:
        raise EducationError("Sign in with an active account to continue.", 403)


def _text(values, key, maximum, *, required=True, default=""):
    value = str(values.get(key, default) or "").strip()
    if (required and not value) or len(value) > maximum:
        raise EducationError(f"Enter {key.replace('_', ' ')} (up to {maximum} characters).")
    if "\x00" in value:
        raise EducationError("Remove invalid characters from your text.")
    return value


def _number(value, label, minimum, maximum):
    if isinstance(value, bool) or not re.fullmatch(r"-?[0-9]+", str(value)):
        raise EducationError(f"Enter a whole number for {label}.")
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise EducationError(f"Enter a whole number for {label}.") from None
    if not minimum <= result <= maximum:
        raise EducationError(f"{label.capitalize()} must be between {minimum} and {maximum}.")
    return result


def _boolean(value):
    return value is True or str(value).lower() in {"true", "1", "on", "yes"}


def resource_url(value, *, required=False):
    """Validate an HTTPS resource link; reject credentials, local hosts and controls."""
    value = str(value or "").strip()
    if not value and not required:
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        bad_host = host in {"localhost", "localhost.localdomain"} or host.endswith(
            (".localhost", ".local", ".internal")
        )
        try:
            bad_host = bad_host or not ip_address(host).is_global
        except ValueError:
            labels = host.encode("idna").decode("ascii").split(".")
            # Browsers interpret alternative numeric IP spellings as addresses.
            # Treat DNS names as real labels, with at least one alphabetic label.
            bad_host = bad_host or len(labels) < 2 or all(label.isdigit() for label in labels)
            bad_host = bad_host or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        if (
            parsed.scheme != "https"
            or not host
            or bad_host
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or len(value) > 2048
            or any(ord(char) <= 32 for char in value)
            or "\\" in value
        ):
            raise ValueError
    except ValueError:
        raise EducationError("Use a public HTTPS resource link without credentials.") from None
    return value


def educator_for(db, user):
    """Return the signed-in member's educator application, including pending states."""
    return db.get(EducatorProfile, user.id) if user is not None else None


def can_teach(db, user):
    """Whether an active member currently has approved teaching permission."""
    if user is None or not user.is_active or user.status != UserStatus.ACTIVE:
        return False
    profile = educator_for(db, user)
    return profile is not None and profile.status == "approved"


def _educator(db, user):
    _active(user)
    profile = educator_for(db, user)
    if profile is None or profile.status != "approved":
        raise EducationError(
            "An approved educator account is required to host or publish learning.", 403
        )
    return profile


def _educator_application_fields(values):
    """Normalize a teaching application before either validation or persistence."""
    return {
        "display_name": _text(values, "display_name", 120),
        "headline": _text(values, "headline", 200),
        "bio": _text(values, "bio", 5000),
        "subjects": _text(values, "subjects", 500, required=False),
    }


def educator_application_requires_review(db, user, values):
    """Validate identity edits before a route closes an approved educator's rooms.

    This check performs no mutation or provider call. Invalid applications must
    fail before disrupting active teaching; unchanged approved identities retain
    approval and therefore need no room closure.
    """
    _active(user)
    fields = _educator_application_fields(values)
    profile = educator_for(db, user)
    return bool(
        profile
        and profile.status == "approved"
        and any(getattr(profile, key) != value for key, value in fields.items())
    )


def apply_educator(db, user, values, *, commit=True):
    """Create/update a member's application; identity edits require a new staff review.

    Routes use ``commit=False`` while holding an educator lock across remote
    room closure and permission revocation, then commit the whole database unit.
    """
    _active(user)
    fields = _educator_application_fields(values)
    profile = educator_for(db, user)
    if profile is None:
        profile = EducatorProfile(user_id=user.id, **fields)
        db.add(profile)
    else:
        changed = any(getattr(profile, key) != value for key, value in fields.items())
        for key, value in fields.items():
            setattr(profile, key, value)
        if changed or profile.status in {"pending", "rejected"}:
            profile.status = "pending"
            profile.review_notes = ""
            profile.reviewed_by = None
            profile.reviewed_at = None
    if commit:
        db.commit()
    else:
        db.flush()
    return profile


def validate_educator_review(db, staff, user_id, status, notes=""):
    """Authorize and validate a staff decision before any external room closure.

    Return the unchanged application and normalized private notes. Persistence
    remains in ``review_educator`` after the route has closed affected rooms.
    """
    _active(staff)
    if not staff.is_staff:
        raise EducationError("Staff approval is required.", 403)
    if status not in {"approved", "paused", "rejected"}:
        raise EducationError("Choose Approved, Paused or Rejected.")
    profile = db.get(EducatorProfile, _identifier(user_id))
    if profile is None:
        raise EducationError("This educator application is unavailable.", 404)
    notes = _text({"notes": notes}, "notes", 2000, required=False)
    return profile, notes


def review_educator(db, staff, user_id, status, notes="", *, commit=True):
    """Staff approve/pause/reject an application, retaining a private decision history.

    ``commit=False`` lets a route retain its educator lock through active-room
    closure and this decision. The caller then owns commit/rollback for the unit.
    """
    profile, notes = validate_educator_review(db, staff, user_id, status, notes)
    previous = profile.status
    profile.status, profile.review_notes = status, notes
    profile.reviewed_by, profile.reviewed_at = staff.id, datetime.now(UTC)
    db.add(
        EducatorReview(
            educator_id=profile.user_id,
            reviewer_id=staff.id,
            previous_status=previous,
            status=status,
            notes=notes,
        )
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return profile


def list_educators(db, *, pending=False, user=None):
    """Public approved directory, or the private staff application queue."""
    query = select(EducatorProfile).join(User, User.id == EducatorProfile.user_id)
    if pending:
        _active(user)
        if not user.is_staff:
            raise EducationError("Staff access is required.", 403)
    else:
        query = query.where(
            EducatorProfile.status == "approved",
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    return list(db.scalars(query.order_by(EducatorProfile.created_at.desc()).limit(200)))


def _public_educator_condition():
    return and_(
        EducatorProfile.status == "approved",
        User.is_active.is_(True),
        User.status == UserStatus.ACTIVE,
    )


def can_manage_course(db, user, course):
    """Staff moderation or an approved educator's ownership, with active identity."""
    return bool(
        user
        and user.is_active
        and user.status == UserStatus.ACTIVE
        and (user.is_staff or (course.educator_id == user.id and can_teach(db, user)))
    )


def _manage_course(db, user, course_id):
    _active(user)
    course = db.get(LearningCourse, _identifier(course_id))
    if course is None:
        raise EducationError("This course is unavailable.", 404)
    if not can_manage_course(db, user, course):
        raise EducationError("Only this course's approved educator or staff can edit it.", 403)
    return course


def _course_fields(values):
    level = str(values.get("level", "all"))
    if level not in COURSE_LEVELS:
        raise EducationError("Choose a valid course level.")
    return {
        "title": _text(values, "title", 180),
        "summary": _text(values, "summary", 500),
        "description": _text(values, "description", 20000),
        "category": _text(values, "category", 100, default="General nursing"),
        "level": level,
    }


def create_course(db, user, values):
    """Create a private draft owned by the currently approved educator."""
    profile = _educator(db, user)
    course = LearningCourse(educator_id=profile.user_id, **_course_fields(values))
    db.add(course)
    db.commit()
    return course


def update_course(db, user, course_id, values):
    """Update educator-owned metadata; clients cannot change ownership or status."""
    course = _manage_course(db, user, course_id)
    for key, value in _course_fields(values).items():
        setattr(course, key, value)
    db.commit()
    return course


def list_courses(db, user=None, *, owned=False, category="", limit=100):
    """List published approved-educator courses, or the member's own private drafts."""
    query = select(LearningCourse).options(joinedload(LearningCourse.educator))
    if owned:
        _active(user)
        query = query.where(LearningCourse.educator_id == user.id)
    else:
        query = query.join(EducatorProfile).join(User, User.id == EducatorProfile.user_id)
        query = query.where(LearningCourse.status == "published", _public_educator_condition())
    if category:
        query = query.where(LearningCourse.category == category)
    return list(
        db.scalars(query.order_by(LearningCourse.created_at.desc()).limit(min(200, max(1, limit))))
    )


def get_course(db, course_id, user=None):
    """Get an authorized course; hidden drafts and paused educators return 404."""
    course = db.get(LearningCourse, _identifier(course_id))
    if course is None:
        raise EducationError("This course is unavailable.", 404)
    owner = (
        user
        and user.is_active
        and user.status == UserStatus.ACTIVE
        and (user.id == course.educator_id or user.is_staff)
    )
    educator = db.get(EducatorProfile, course.educator_id)
    teacher = db.get(User, course.educator_id)
    public = (
        course.status == "published"
        and educator
        and educator.status == "approved"
        and teacher
        and teacher.is_active
        and teacher.status == UserStatus.ACTIVE
    )
    if not owner and not public:
        raise EducationError("This course is unavailable.", 404)
    return course


def course_content(db, course_id, user=None):
    """Ordered modules and lessons for an authorized course, with no quiz answer keys."""
    get_course(db, course_id, user)
    modules = list(
        db.scalars(
            select(LearningModule)
            .where(LearningModule.course_id == _identifier(course_id))
            .order_by(LearningModule.position)
        )
    )
    result = []
    for module in modules:
        lessons = list(
            db.scalars(
                select(LearningLesson)
                .where(LearningLesson.module_id == module.id)
                .order_by(LearningLesson.position)
            )
        )
        result.append({"module": module, "lessons": lessons})
    return result


def _next_position(db, model, parent_field, parent_id):
    return (db.scalar(select(func.max(model.position)).where(parent_field == parent_id)) or 0) + 1


def _clear_completion(db, course_id):
    # Changing a curriculum invalidates the old aggregate completion claim; the
    # learner's individual progress stays intact and is recomputed on next use.
    db.execute(
        update(LearningEnrollment)
        .where(LearningEnrollment.course_id == course_id)
        .values(completed_at=None)
    )


def _withdraw_unusable_curriculum(db, course):
    """Keep publication truthful when an editor removes usable course content."""
    if course.status != "published":
        return
    db.flush()
    lessons = list(
        db.scalars(
            select(LearningLesson).join(LearningModule).where(LearningModule.course_id == course.id)
        )
    )
    missing_quiz = any(
        lesson.kind == "quiz"
        and not db.scalar(
            select(QuizQuestion.id).where(QuizQuestion.lesson_id == lesson.id).limit(1)
        )
        for lesson in lessons
    )
    if not lessons or missing_quiz:
        # The editor must explicitly publish again after completing the changed
        # curriculum. Enrollment and historical attempts remain preserved.
        course.status = "draft"


def save_module(db, user, course_id, values, module_id=None):
    """Create/edit one ordered module; enforce course ownership and unique positions."""
    course = _manage_course(db, user, course_id)
    module = db.get(LearningModule, _identifier(module_id)) if module_id else None
    if module_id and (module is None or module.course_id != course.id):
        raise EducationError("This module is unavailable.", 404)
    default = (
        module.position
        if module
        else _next_position(db, LearningModule, LearningModule.course_id, course.id)
    )
    fields = {
        "title": _text(values, "title", 180),
        "position": _number(values.get("position") or default, "position", 1, 1000),
    }
    if module is None:
        module = LearningModule(course_id=course.id, **fields)
        db.add(module)
    else:
        for key, value in fields.items():
            setattr(module, key, value)
    _clear_completion(db, course.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EducationError("Another module already uses that position.") from None
    return module


def _lesson(db, lesson_id):
    lesson = db.get(LearningLesson, _identifier(lesson_id))
    if lesson is None:
        raise EducationError("This lesson is unavailable.", 404)
    return lesson, lesson.module.course


def _lock_lesson_revision(db, lesson_id):
    """Serialize assessment edits/grading on both PostgreSQL and SQLite.

    A no-op UPDATE acquires the row/write lock before reading the revision.
    Preserving updated_at avoids making a quiz attempt look like an author edit.
    Editors take this same lock before invalidating old completion records.
    """
    result = db.execute(
        update(LearningLesson)
        .where(LearningLesson.id == lesson_id)
        .values(revision=LearningLesson.revision, updated_at=LearningLesson.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise EducationError("This lesson is unavailable.", 404)
    lesson = db.get(LearningLesson, lesson_id)
    db.refresh(lesson)
    return lesson


def get_lesson(db, lesson_id, user=None):
    """Get lesson content only for an enrolled learner or its authorized editor."""
    lesson, course = _lesson(db, lesson_id)
    get_course(db, course.id, user)
    if not can_manage_course(db, user, course):
        _active(user)
        if db.get(LearningEnrollment, (course.id, user.id)) is None:
            raise EducationError("Enroll in this course to open its lessons.", 403)
    return lesson


def save_lesson(db, user, module_id, values, lesson_id=None):
    """Edit owned learning content; external resources must be safe HTTPS links."""
    module = db.get(LearningModule, _identifier(module_id))
    if module is None:
        raise EducationError("This module is unavailable.", 404)
    course = _manage_course(db, user, module.course_id)
    lesson = db.get(LearningLesson, _identifier(lesson_id)) if lesson_id else None
    if lesson_id and (lesson is None or lesson.module_id != module.id):
        raise EducationError("This lesson is unavailable.", 404)
    if lesson is not None:
        lesson = _lock_lesson_revision(db, lesson.id)
    kind = str(values.get("kind", "text"))
    if kind not in LESSON_KINDS:
        raise EducationError("Choose Text, Resource, Video or Quiz.")
    content = _text(values, "content", 30000, required=kind == "text")
    link = resource_url(values.get("resource_url"), required=kind in {"resource", "video"})
    default = (
        lesson.position
        if lesson
        else _next_position(db, LearningLesson, LearningLesson.module_id, module.id)
    )
    fields = {
        "title": _text(values, "title", 180),
        "kind": kind,
        "content": content,
        "resource_url": link,
        "position": _number(values.get("position") or default, "position", 1, 1000),
        "duration_minutes": _number(values.get("duration_minutes") or 0, "duration", 0, 1440),
        "pass_percentage": _number(values.get("pass_percentage") or 70, "pass percentage", 1, 100),
    }
    if lesson is None:
        lesson = LearningLesson(module_id=module.id, **fields)
        db.add(lesson)
    else:
        revised_content = any(
            getattr(lesson, key) != fields[key]
            for key in ("kind", "content", "resource_url", "pass_percentage")
        )
        for key, value in fields.items():
            setattr(lesson, key, value)
        if revised_content:
            lesson.revision += 1
            db.execute(delete(LessonProgress).where(LessonProgress.lesson_id == lesson.id))
    _clear_completion(db, course.id)
    try:
        _withdraw_unusable_curriculum(db, course)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EducationError("Another lesson already uses that position.") from None
    return lesson


def delete_learning_item(db, user, kind, identifier):
    """Remove an owned module, lesson or question and invalidate course completion."""
    if kind == "module":
        item = db.get(LearningModule, _identifier(identifier))
        course_id = item.course_id if item else None
    elif kind == "lesson":
        item = db.get(LearningLesson, _identifier(identifier))
        course_id = item.module.course_id if item else None
    elif kind == "question":
        item = db.get(QuizQuestion, _identifier(identifier))
        course_id = _lesson(db, item.lesson_id)[1].id if item else None
    else:
        raise EducationError("Choose a valid learning item.")
    if item is None:
        raise EducationError("This learning item is unavailable.", 404)
    course = _manage_course(db, user, course_id)
    if kind == "question":
        _lock_lesson_revision(db, item.lesson_id)
    _clear_completion(db, course_id)
    if kind == "question":
        lesson, _ = _lesson(db, item.lesson_id)
        lesson.revision += 1
        db.execute(delete(LessonProgress).where(LessonProgress.lesson_id == item.lesson_id))
    db.delete(item)
    _withdraw_unusable_curriculum(db, course)
    db.commit()


def set_course_status(db, user, course_id, status):
    """Explicitly publish a usable curriculum or withdraw/archive an owned course."""
    course = _manage_course(db, user, course_id)
    if status not in {"draft", "published", "archived"}:
        raise EducationError("Choose Draft, Published or Archived.")
    if status == "published":
        if not can_teach(db, db.get(User, course.educator_id)):
            raise EducationError("The course educator must be approved before publication.")
        sections = course_content(db, course.id, user)
        lessons = [lesson for section in sections for lesson in section["lessons"]]
        if not lessons:
            raise EducationError("Add at least one lesson before publishing.")
        for lesson in lessons:
            if lesson.kind == "quiz" and not db.scalar(
                select(QuizQuestion.id).where(QuizQuestion.lesson_id == lesson.id).limit(1)
            ):
                raise EducationError("Add questions to every quiz before publishing.")
    course.status = status
    db.commit()
    return course


def enroll(db, user, course_id):
    """Idempotently enroll an active learner in a currently published course."""
    _active(user)
    course = get_course(db, course_id, user)
    if course.status != "published":
        raise EducationError("This course is not open for enrollment.")
    enrollment = db.get(LearningEnrollment, (course.id, user.id))
    if enrollment:
        return enrollment
    enrollment = LearningEnrollment(course_id=course.id, user_id=user.id)
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        enrollment = db.get(LearningEnrollment, (course.id, user.id))
        if enrollment is None:
            raise EducationError("Enrollment could not be saved. Try again.") from None
    return enrollment


def my_enrollments(db, user):
    """Private enrollments, including unavailable courses so saved history is visible."""
    _active(user)
    return list(
        db.scalars(
            select(LearningEnrollment)
            .options(joinedload(LearningEnrollment.course).joinedload(LearningCourse.educator))
            .where(LearningEnrollment.user_id == user.id)
            .order_by(LearningEnrollment.created_at.desc())
        )
    )


def course_progress(db, user, course_id):
    """Learner-only progress totals; self-reported completion is not attendance."""
    _active(user)
    get_course(db, course_id, user)
    lessons = list(
        db.scalars(
            select(LearningLesson)
            .join(LearningModule)
            .where(LearningModule.course_id == _identifier(course_id))
        )
    )
    identifiers = {lesson.id for lesson in lessons}
    rows = (
        list(
            db.scalars(
                select(LessonProgress).where(
                    LessonProgress.user_id == user.id, LessonProgress.lesson_id.in_(identifiers)
                )
            )
        )
        if identifiers
        else []
    )
    completed_ids = {row.lesson_id for row in rows}
    enrollment = db.get(LearningEnrollment, (_identifier(course_id), user.id))
    return {
        "total": len(lessons),
        "completed": len(completed_ids),
        "percent": len(completed_ids) * 100 // len(lessons) if lessons else 0,
        "completed_lesson_ids": completed_ids,
        "completed_at": enrollment.completed_at if enrollment else None,
    }


def _complete_lesson(db, user, lesson, course, basis):
    row = db.get(LessonProgress, (lesson.id, user.id))
    if row is None:
        row = LessonProgress(
            lesson_id=lesson.id,
            user_id=user.id,
            completed_at=datetime.now(UTC),
            completion_basis=basis,
        )
        db.add(row)
    elif basis == "quiz":
        row.completion_basis = "quiz"
    db.flush()
    total = db.scalar(
        select(func.count())
        .select_from(LearningLesson)
        .join(LearningModule)
        .where(LearningModule.course_id == course.id)
    )
    done = db.scalar(
        select(func.count())
        .select_from(LessonProgress)
        .join(LearningLesson)
        .join(LearningModule)
        .where(LearningModule.course_id == course.id, LessonProgress.user_id == user.id)
    )
    enrollment = db.get(LearningEnrollment, (course.id, user.id))
    if enrollment and total and done == total and enrollment.completed_at is None:
        enrollment.completed_at = datetime.now(UTC)
    return row


def mark_lesson_complete(db, user, lesson_id):
    """Record self-reported reading only; quiz lessons require server-scored passing."""
    lesson = get_lesson(db, lesson_id, user)
    course = lesson.module.course
    if db.get(LearningEnrollment, (course.id, user.id)) is None:
        raise EducationError("Enroll before recording learning progress.", 403)
    questions = db.scalar(
        select(QuizQuestion.id).where(QuizQuestion.lesson_id == lesson.id).limit(1)
    )
    if lesson.kind == "quiz" or questions:
        raise EducationError("Pass the lesson quiz to complete this lesson.")
    row = _complete_lesson(db, user, lesson, course, "self-reported")
    db.commit()
    return row


def save_quiz_question(db, user, lesson_id, values, question_id=None):
    """Author a private answer key; options are 2–6 nonempty plain-text strings."""
    lesson, course = _lesson(db, lesson_id)
    _manage_course(db, user, course.id)
    lesson = _lock_lesson_revision(db, lesson.id)
    question = db.get(QuizQuestion, _identifier(question_id)) if question_id else None
    if question_id and (question is None or question.lesson_id != lesson.id):
        raise EducationError("This quiz question is unavailable.", 404)
    raw_options = values.get("options", [])
    if isinstance(raw_options, str):
        raw_options = raw_options.splitlines()
    if not isinstance(raw_options, (list, tuple)):
        raise EducationError("Enter one answer option per line.")
    options = [str(value).strip() for value in raw_options if str(value).strip()]
    if (
        not 2 <= len(options) <= 6
        or any(len(value) > 1000 for value in options)
        or len(set(options)) != len(options)
    ):
        raise EducationError(
            "Provide two to six different answer options (up to 1000 characters each)."
        )
    default = (
        question.position
        if question
        else _next_position(db, QuizQuestion, QuizQuestion.lesson_id, lesson.id)
    )
    fields = {
        "prompt": _text(values, "prompt", 2000),
        "options": options,
        "correct_index": _number(
            values.get("correct_index"), "correct answer index", 0, len(options) - 1
        ),
        "explanation": _text(values, "explanation", 3000, required=False),
        "position": _number(values.get("position") or default, "position", 1, 1000),
    }
    changed_definition = question is None or any(
        getattr(question, key) != fields[key]
        for key in ("prompt", "options", "correct_index", "explanation")
    )
    if question is None:
        question = QuizQuestion(lesson_id=lesson.id, **fields)
        db.add(question)
    else:
        for key, value in fields.items():
            setattr(question, key, value)
    if changed_definition:
        # An integer revision identifies a changed assessment without exposing a
        # digest that could be used to brute-force its private answer keys.
        lesson.revision += 1
        _clear_completion(db, course.id)
        db.execute(delete(LessonProgress).where(LessonProgress.lesson_id == lesson.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EducationError("Another question already uses that position.") from None
    return question


def quiz_questions(db, user, lesson_id, include_answers=False):
    """Safe learner dictionaries; answer keys require explicit authorized editing."""
    lesson = get_lesson(db, lesson_id, user)
    if include_answers and not can_manage_course(db, user, lesson.module.course):
        raise EducationError("Only this course's editor can view answer keys.", 403)
    rows = db.scalars(
        select(QuizQuestion)
        .where(QuizQuestion.lesson_id == lesson.id)
        .order_by(QuizQuestion.position)
    )
    result = []
    for row in rows:
        item = {"id": row.id, "prompt": row.prompt, "options": list(row.options)}
        if include_answers:
            item.update(
                correct_index=row.correct_index, explanation=row.explanation, position=row.position
            )
        result.append(item)
    return result


def quiz_revision(db, user, lesson_id):
    """Return the authorized lesson version used to reject stale browser submissions."""
    return get_lesson(db, lesson_id, user).revision


def submit_quiz(db, user, lesson_id, answers, request_id=None, lesson_revision=None):
    """Score the current revision server-side; stale forms/old request IDs raise 409."""
    lesson = get_lesson(db, lesson_id, user)
    course = lesson.module.course
    if db.get(LearningEnrollment, (course.id, user.id)) is None:
        raise EducationError("Enroll before taking this lesson's quiz.", 403)
    lesson = _lock_lesson_revision(db, lesson.id)
    if lesson_revision is not None:
        supplied_revision = _number(lesson_revision, "lesson revision", 1, 2_147_483_647)
        if supplied_revision != lesson.revision:
            raise EducationError("This lesson changed. Refresh it before starting a new quiz.", 409)
    request_id = str(request_id or uuid4())
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        raise EducationError("Open a new quiz form and try again.")
    previous = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.lesson_id == lesson.id,
            QuizAttempt.user_id == user.id,
            QuizAttempt.request_id == request_id,
        )
    )
    if previous and previous.lesson_revision != lesson.revision:
        raise EducationError(
            "This quiz attempt belongs to an earlier lesson. Start a new attempt.", 409
        )
    rows = list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.lesson_id == lesson.id)
            .order_by(QuizQuestion.position)
        )
    )
    if not rows:
        raise EducationError("This lesson has no published quiz questions.")
    if not isinstance(answers, dict):
        raise EducationError("Submit one answer for every question.")
    normalized = {}
    for question in rows:
        value = answers.get(str(question.id), answers.get(question.id))
        normalized[str(question.id)] = _number(value, "answer", 0, len(question.options) - 1)
    if len(answers) != len(rows):
        raise EducationError("Submit answers only for this lesson's questions.")
    if previous:
        if previous.answers != normalized:
            raise EducationError("This quiz submission was already used. Start a new attempt.", 409)
        return previous
    score = sum(normalized[str(question.id)] == question.correct_index for question in rows)
    passed = score * 100 >= len(rows) * lesson.pass_percentage
    attempt = QuizAttempt(
        lesson_id=lesson.id,
        user_id=user.id,
        request_id=request_id,
        lesson_revision=lesson.revision,
        answers=normalized,
        score=score,
        total=len(rows),
        passed=passed,
    )
    db.add(attempt)
    if passed:
        _complete_lesson(db, user, lesson, course, "quiz")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(
            select(QuizAttempt).where(
                QuizAttempt.lesson_id == lesson.id,
                QuizAttempt.user_id == user.id,
                QuizAttempt.request_id == request_id,
            )
        )
        if (
            previous
            and previous.answers == normalized
            and previous.lesson_revision == lesson.revision
        ):
            return previous
        raise EducationError("The quiz could not be saved. Try again.") from None
    return attempt


def quiz_attempt_feedback(db, user, attempt):
    """Own-attempt feedback for the current assessment, without answer indices.

    Explanations become available after a learner submits an attempt. Historical
    attempts remain evidence, but cannot be explained against revised questions
    or answer keys. The course/lesson access check also respects withdrawal.
    """
    _active(user)
    if attempt.user_id != user.id:
        raise EducationError("Only your own quiz attempt is available.", 403)
    lesson = get_lesson(db, attempt.lesson_id, user)
    if attempt.lesson_revision != lesson.revision:
        raise EducationError("This quiz changed. Start a current attempt for feedback.", 409)
    questions = db.scalars(
        select(QuizQuestion).where(QuizQuestion.lesson_id == lesson.id)
    )
    return {
        question.id: {
            "correct": attempt.answers.get(str(question.id)) == question.correct_index,
            "explanation": question.explanation,
        }
        for question in questions
    }


def get_module(db, module_id, user=None):
    """Resolve a module only for an authorized course editor."""
    module = db.get(LearningModule, _identifier(module_id))
    if module is None:
        raise EducationError("This module is unavailable.", 404)
    _manage_course(db, user, module.course_id)
    return module


def _session_fields(values, *, now=None):
    timezone = str(values.get("timezone", "Africa/Lagos") or "Africa/Lagos")
    try:
        local_zone = ZoneInfo(timezone)
        times = {}
        for key in ("starts_at", "ends_at"):
            value = values.get(key)
            value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            if value.tzinfo is None:
                original = value
                value = value.replace(tzinfo=local_zone)
                if value.astimezone(UTC).astimezone(local_zone).replace(tzinfo=None) != original:
                    raise ValueError
            times[key] = utc(value)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise EducationError(
            "Enter valid session dates and an IANA timezone such as Africa/Lagos."
        ) from None
    if times["ends_at"] <= times["starts_at"]:
        raise EducationError("The session must end after it starts.")
    if times["ends_at"] <= (now or datetime.now(UTC)):
        raise EducationError("Choose a session end time in the future.")
    session_format = str(values.get("session_format", "lecture"))
    if session_format not in SESSION_FORMATS:
        raise EducationError("Choose Lecture or Discussion.")
    return {
        "title": _text(values, "title", 180),
        "description": _text(values, "description", 12000),
        "objectives": _text(values, "objectives", 5000, required=False),
        "timezone": timezone,
        **times,
        "session_format": session_format,
        "capacity": _number(values.get("capacity") or 50, "capacity", 1, 1000),
        "recording_enabled": _boolean(values.get("recording_enabled")),
        "chat_enabled": _boolean(values.get("chat_enabled", True)),
    }


def can_manage_session(db, user, session):
    """Active staff moderation or approved educator ownership of this session."""
    return bool(
        user
        and user.is_active
        and user.status == UserStatus.ACTIVE
        and (user.is_staff or (session.educator_id == user.id and can_teach(db, user)))
    )


def _manage_session(db, user, session_id):
    _active(user)
    session = db.get(LearningSession, _identifier(session_id))
    if session is None:
        raise EducationError("This live session is unavailable.", 404)
    if not can_manage_session(db, user, session):
        raise EducationError("Only this session's approved educator or staff can manage it.", 403)
    return session


def create_session(db, user, values):
    """Create a standalone or owned-course session; scheduling is explicit."""
    profile = _educator(db, user)
    course_id = values.get("course_id")
    course = _manage_course(db, user, course_id) if course_id else None
    if course and course.educator_id != user.id:
        raise EducationError("Associate a session with one of your own courses.", 403)
    state = str(values.get("status", "draft"))
    if state not in {"draft", "scheduled"}:
        raise EducationError("New sessions must be Draft or Scheduled.")
    if state == "scheduled" and course and course.status != "published":
        raise EducationError("Publish the associated course before scheduling its live session.")
    session = LearningSession(
        educator_id=profile.user_id,
        course_id=course.id if course else None,
        status=state,
        **_session_fields(values),
    )
    db.add(session)
    db.commit()
    return session


def update_session(db, user, session_id, values):
    """Edit a draft/scheduled session; preserve lifecycle and already reserved seats."""
    session = _manage_session(db, user, session_id)
    if session.status not in {"draft", "scheduled"}:
        raise EducationError("Only draft or scheduled sessions can be edited.")
    fields = _session_fields(values)
    if fields["capacity"] < session.reserved_count:
        raise EducationError("Capacity cannot be lower than the seats already reserved.")
    raw_course = values.get("course_id", session.course_id)
    course = _manage_course(db, user, raw_course) if raw_course else None
    if course and course.educator_id != session.educator_id:
        raise EducationError("Use a course owned by this session's educator.")
    if session.status == "scheduled" and course and course.status != "published":
        raise EducationError("The associated course must be published.")
    if (course.id if course else None) != session.course_id and session.reserved_count:
        raise EducationError("The course cannot change after members reserve seats.")
    if fields["session_format"] != session.session_format:
        # Set the initial speaking policy for every reserved learner before the
        # room opens. Once live, host moderation owns each permission separately.
        db.execute(
            update(SessionRegistration)
            .where(SessionRegistration.session_id == session.id)
            .values(speaker_allowed=fields["session_format"] == "discussion", hand_raised_at=None)
        )
    session.course_id = course.id if course else None
    for key, value in fields.items():
        setattr(session, key, value)
    db.commit()
    return session


def list_sessions(db, user=None, *, owned=False, include_past=False, limit=100):
    """Upcoming public sessions or an educator's complete private schedule."""
    query = select(LearningSession).options(
        joinedload(LearningSession.educator), joinedload(LearningSession.course)
    )
    if owned:
        _active(user)
        query = query.where(LearningSession.educator_id == user.id)
    else:
        query = query.join(EducatorProfile).join(User, User.id == EducatorProfile.user_id)
        query = query.where(
            LearningSession.status.in_(["scheduled", "live", "ended"]), _public_educator_condition()
        )
        query = query.outerjoin(
            LearningCourse, LearningCourse.id == LearningSession.course_id
        ).where(or_(LearningSession.course_id.is_(None), LearningCourse.status == "published"))
        if not include_past:
            query = query.where(LearningSession.ends_at > datetime.now(UTC))
    return list(
        db.scalars(
            query.order_by(LearningSession.starts_at, LearningSession.id).limit(
                min(200, max(1, limit))
            )
        )
    )


def get_session(db, session_id, user=None):
    """Get public scheduled/live history or the educator's private authoring record."""
    session = db.get(LearningSession, _identifier(session_id))
    if session is None:
        raise EducationError("This live session is unavailable.", 404)
    owner = (
        user
        and user.is_active
        and user.status == UserStatus.ACTIVE
        and (user.id == session.educator_id or user.is_staff)
    )
    profile, teacher = (
        db.get(EducatorProfile, session.educator_id),
        db.get(User, session.educator_id),
    )
    published_course = not session.course_id or (
        session.course and session.course.status == "published"
    )
    public = (
        session.status != "draft"
        and profile
        and profile.status == "approved"
        and teacher
        and teacher.is_active
        and teacher.status == UserStatus.ACTIVE
        and published_course
    )
    if not owner and not public:
        raise EducationError("This live session is unavailable.", 404)
    return session


def register_session(db, user, session_id):
    """Atomically reserve a seat; duplicate requests consume exactly one allocation."""
    _active(user)
    session = get_session(db, session_id, user)
    if session.educator_id == user.id:
        raise EducationError("You host this session and do not need a learner seat.")
    if session.course_id and db.get(LearningEnrollment, (session.course_id, user.id)) is None:
        raise EducationError("Enroll in the associated course before reserving a seat.", 403)
    now = datetime.now(UTC)
    if session.status not in {"scheduled", "live"} or utc(session.ends_at) <= now:
        raise EducationError("This session no longer accepts reservations.")
    previous = db.get(SessionRegistration, (session.id, user.id))
    if previous and previous.status == "reserved":
        return previous
    if previous and previous.status == "removed":
        raise EducationError("The host removed your access to this session.", 403)
    # The capacity predicate and increment are one statement. PostgreSQL locks
    # the session row; SQLite serializes this write. A duplicate unique-key
    # insert rolls back its increment in the same transaction.
    result = db.execute(
        update(LearningSession)
        .where(
            LearningSession.id == session.id,
            LearningSession.status.in_(["scheduled", "live"]),
            LearningSession.ends_at > now,
            LearningSession.reserved_count < LearningSession.capacity,
        )
        .values(reserved_count=LearningSession.reserved_count + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise EducationError("This session is full or no longer accepts reservations.")
    if previous:
        previous.status, previous.speaker_allowed = (
            "reserved",
            session.session_format == "discussion",
        )
        previous.hand_raised_at = None
        registration = previous
    else:
        registration = SessionRegistration(
            session_id=session.id,
            user_id=user.id,
            speaker_allowed=session.session_format == "discussion",
        )
        db.add(registration)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        registration = db.get(SessionRegistration, (session.id, user.id))
        if registration is None or registration.status != "reserved":
            raise EducationError("The reservation could not be saved. Try again.") from None
    db.refresh(session)
    return registration


def _release_seat(db, session_id, user_id, status):
    changed = db.execute(
        update(SessionRegistration)
        .where(
            SessionRegistration.session_id == session_id,
            SessionRegistration.user_id == user_id,
            SessionRegistration.status == "reserved",
        )
        .values(status=status, speaker_allowed=False, hand_raised_at=None)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount:
        db.execute(
            update(LearningSession)
            .where(LearningSession.id == session_id, LearningSession.reserved_count > 0)
            .values(reserved_count=LearningSession.reserved_count - 1)
            .execution_options(synchronize_session=False)
        )
    return bool(changed.rowcount)


def cancel_registration(db, user, session_id):
    """Idempotently withdraw the member's own reservation and release its seat."""
    _active(user)
    session = get_session(db, session_id, user)
    _release_seat(db, session.id, user.id, "cancelled")
    db.commit()
    db.expire_all()
    return db.get(SessionRegistration, (session.id, user.id))


def session_registrations(db, user, session_id=None):
    """Private member reservations, or a host-only roster with moderation state."""
    _active(user)
    query = select(SessionRegistration).options(
        joinedload(SessionRegistration.session).joinedload(LearningSession.educator)
    )
    if session_id is not None:
        session = _manage_session(db, user, session_id)
        query = query.where(SessionRegistration.session_id == session.id)
    else:
        query = query.where(SessionRegistration.user_id == user.id)
    return list(db.scalars(query.order_by(SessionRegistration.created_at.desc()).limit(1000)))


def change_session_state(
    db, user, session_id, state, *, allow_early=False, now=None, commit=True
):
    """Apply valid lifecycle transitions after provider API success where required.

    Starting is allowed within fifteen minutes of the scheduled time, before
    its end. Only staff may explicitly override the early-start boundary.
    Provider room creation/deletion belongs to the route's provider adapter.
    """
    session = _manage_session(db, user, session_id)
    if state == session.status:
        return session
    now = now or datetime.now(UTC)
    if state in {"scheduled", "live"} and not can_teach(db, db.get(User, session.educator_id)):
        raise EducationError("The session educator must currently be approved.")
    if state in {"scheduled", "live"} and session.course and session.course.status != "published":
        raise EducationError("The associated course must be published before opening its session.")
    if state == "scheduled" and session.status == "draft":
        if utc(session.ends_at) <= now or (session.course and session.course.status != "published"):
            raise EducationError(
                "Use a future session time and a published course before scheduling."
            )
    elif state == "live" and session.status == "scheduled":
        if utc(session.ends_at) <= now:
            raise EducationError("This session's scheduled end has passed.")
        if now < utc(session.starts_at) - timedelta(minutes=15) and not (
            user.is_staff and allow_early
        ):
            raise EducationError("The room can open fifteen minutes before the scheduled start.")
    elif state == "ended" and session.status == "live":
        pass
    elif state == "ended" and session.status == "scheduled" and now >= utc(session.ends_at):
        pass
    elif state == "cancelled" and session.status in {"draft", "scheduled", "live"}:
        db.execute(
            update(SessionRegistration)
            .where(
                SessionRegistration.session_id == session.id,
                SessionRegistration.status == "reserved",
            )
            .values(status="cancelled", speaker_allowed=False, hand_raised_at=None)
            .execution_options(synchronize_session=False)
        )
        session.reserved_count = 0
    else:
        raise EducationError("This session cannot make that state change.")
    session.status = state
    db.add(SessionModeration(session_id=session.id, actor_id=user.id, action="state:" + state))
    if commit:
        db.commit()
    else:
        # A permission-revocation route can close several rooms while retaining
        # its educator lock. Accepted remote closures are retried idempotently
        # if the enclosing database transaction later needs to roll back.
        db.flush()
    return session


def _participant(db, user, session_id):
    _active(user)
    session = get_session(db, session_id, user)
    if can_manage_session(db, user, session):
        return session, None, True
    registration = db.get(SessionRegistration, (session.id, user.id))
    if registration is None or registration.status != "reserved":
        raise EducationError("Reserve a seat to access this learning session.", 403)
    if session.course_id and db.get(LearningEnrollment, (session.course_id, user.id)) is None:
        raise EducationError("Current course enrollment is required.", 403)
    return session, registration, False


def join_session(db, user, session_id, *, now=None):
    """Authoritative live-room access and publish rights; clients cannot self-promote."""
    session, registration, host = _participant(db, user, session_id)
    now = now or datetime.now(UTC)
    if session.status != "live" or utc(session.ends_at) <= now:
        raise EducationError("The educator has not opened this room or the session has ended.")
    return {
        "session": session,
        "role": "host" if host else "attendee",
        "identity": str(user.id),
        "can_publish": bool(host or (registration and registration.speaker_allowed)),
        "can_subscribe": True,
        "can_publish_data": False,
    }


def send_session_message(db, user, session_id, body, kind="question"):
    """Registered participants submit plain-text questions or permitted live chat."""
    session, _, host = _participant(db, user, session_id)
    if kind not in {"question", "chat"}:
        raise EducationError("Choose Question or Chat.")
    if session.status not in {"scheduled", "live"}:
        raise EducationError("This session no longer accepts messages.")
    if kind == "chat" and (session.status != "live" or (not session.chat_enabled and not host)):
        raise EducationError("Chat is unavailable for this session.")
    recent = db.scalar(
        select(func.count())
        .select_from(SessionMessage)
        .where(
            SessionMessage.user_id == user.id,
            SessionMessage.session_id == session.id,
            SessionMessage.created_at > datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    if recent >= 20:
        raise EducationError("Please wait a minute before sending more messages.", 429)
    message = SessionMessage(
        session_id=session.id, user_id=user.id, kind=kind, body=_text({"body": body}, "body", 2000)
    )
    db.add(message)
    db.commit()
    return message


def session_messages(db, user, session_id, *, include_hidden=False, limit=200):
    """Participant-only discussion history; hidden messages are host-only."""
    session, _, host = _participant(db, user, session_id)
    if include_hidden and not host:
        raise EducationError("Only the host can review hidden messages.", 403)
    query = select(SessionMessage).where(SessionMessage.session_id == session.id)
    if not include_hidden:
        query = query.where(SessionMessage.status == "visible")
    rows = list(
        db.scalars(
            query.order_by(SessionMessage.created_at.desc(), SessionMessage.id.desc()).limit(
                min(500, max(1, limit))
            )
        )
    )
    return list(reversed(rows))


def moderate_message(db, user, message_id, action, answer=""):
    """The session host/staff may hide, restore or answer a session question."""
    message = db.get(SessionMessage, _identifier(message_id))
    if message is None:
        raise EducationError("This session message is unavailable.", 404)
    session = _manage_session(db, user, message.session_id)
    if action in {"hide", "restore"}:
        message.status = "hidden" if action == "hide" else "visible"
    elif action == "answer" and message.kind == "question":
        message.answer = _text({"answer": answer}, "answer", 5000)
        message.answered_by, message.answered_at = user.id, datetime.now(UTC)
    else:
        raise EducationError("Choose a valid message action.")
    db.add(
        SessionModeration(
            session_id=session.id,
            actor_id=user.id,
            target_id=message.user_id,
            action="message:" + action,
        )
    )
    db.commit()
    return message


def set_hand_raise(db, user, session_id, raised):
    """A reserved participant may raise/lower their hand while the room is live."""
    session, registration, host = _participant(db, user, session_id)
    if host or registration is None:
        raise EducationError("Hosts manage speaking without raising a learner hand.")
    if session.status != "live" or utc(session.ends_at) <= datetime.now(UTC):
        raise EducationError("Raise your hand while the session is live.")
    registration.hand_raised_at = datetime.now(UTC) if _boolean(raised) else None
    db.commit()
    return registration


def moderate_participant(db, user, session_id, participant_id, action):
    """Record host-controlled speaking/removal; provider permission update is separate."""
    session = _manage_session(db, user, session_id)
    participant_id = _identifier(participant_id)
    registration = db.get(SessionRegistration, (session.id, participant_id))
    if registration is None or registration.status != "reserved":
        raise EducationError("This participant has no active reservation.", 404)
    if action == "remove":
        _release_seat(db, session.id, participant_id, "removed")
    elif action in {"allow_speaking", "revoke_speaking", "clear_hand"}:
        if action != "clear_hand":
            registration.speaker_allowed = action == "allow_speaking"
        registration.hand_raised_at = None
    else:
        raise EducationError("Choose a valid participant action.")
    db.add(
        SessionModeration(
            session_id=session.id,
            actor_id=user.id,
            target_id=participant_id,
            action="participant:" + action,
        )
    )
    db.commit()
    db.expire_all()
    return db.get(SessionRegistration, (session.id, participant_id))


def recording_for(db, user, recording_id):
    """Authorize private playback for a host or a currently reserved participant."""
    recording = db.get(LearningRecording, _identifier(recording_id))
    if recording is None:
        raise EducationError("This recording is unavailable.", 404)
    session, _, _ = _participant(db, user, recording.session_id)
    if not session.recording_enabled or recording.status != "complete" or not recording.storage_key:
        raise EducationError("This recording is not available for playback.", 404)
    return recording


def session_recordings(db, user, session_id):
    """Private session recording metadata, never unrestricted object URLs."""
    session, _, host = _participant(db, user, session_id)
    query = select(LearningRecording).where(LearningRecording.session_id == session.id)
    if not host:
        query = query.where(LearningRecording.status == "complete")
    return list(db.scalars(query.order_by(LearningRecording.created_at)))


def register_recording(db, user, session_id, provider_result):
    """Persist provider-accepted egress metadata; this does not claim a completed recording."""
    session = _manage_session(db, user, session_id)
    if session.status != "live" or not session.recording_enabled:
        raise EducationError("Recording must be enabled for a live session.")
    egress_id = str(provider_result.get("egress_id", ""))
    key = _recording_key(session.id, provider_result.get("object_key", ""))
    if not egress_id or len(egress_id) > 128 or not key:
        raise EducationError("The provider did not return valid private recording metadata.")
    recording = db.scalar(
        select(LearningRecording).where(LearningRecording.provider_egress_id == egress_id)
    )
    if recording:
        if recording.session_id != session.id:
            raise EducationError("This recording belongs to another session.")
        return recording
    recording = LearningRecording(
        session_id=session.id, provider_egress_id=egress_id, storage_key=key, status="starting"
    )
    db.add(recording)
    db.commit()
    return recording


def _recording_key(session_id, value):
    value = str(value or "")
    prefix = f"learning/{session_id}/"
    if not value.startswith(prefix) or len(value) > 2048:
        return ""
    suffix = value[len(prefix) :]
    return (
        value
        if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.mp4", suffix) and ".." not in suffix
        else ""
    )


def _attendance_seconds(row):
    if row.left_at is not None:
        row.seconds = max(0, int((utc(row.left_at) - utc(row.joined_at)).total_seconds()))


def _provider_attendance(db, session, event_type, payload, occurred_at):
    participant = payload.get("participant") or {}
    try:
        identity = UUID(str(participant.get("identity", "")))
    except (ValueError, TypeError):
        return
    sid = str(participant.get("sid", ""))
    if not sid or len(sid) > 128:
        return
    member = db.get(User, identity)
    if member is None:
        return
    row = db.scalar(
        select(LearningAttendance).where(
            LearningAttendance.session_id == session.id, LearningAttendance.participant_sid == sid
        )
    )
    if row is not None and row.user_id != identity:
        raise EducationError("Provider attendance identity conflicts with its connection.")
    if event_type == "participant_joined":
        if occurred_at < utc(session.starts_at) - timedelta(minutes=15) or occurred_at > utc(
            session.ends_at
        ):
            return
        registration = db.get(SessionRegistration, (session.id, identity))
        authorized = can_manage_session(db, member, session) or (
            registration and registration.status == "reserved"
        )
        if not authorized:
            return
        if row is None:
            row = LearningAttendance(
                session_id=session.id, user_id=identity, participant_sid=sid, joined_at=occurred_at
            )
            db.add(row)
        elif occurred_at < utc(row.joined_at):
            row.joined_at = occurred_at
        _attendance_seconds(row)
    elif event_type == "participant_left":
        if row is None:
            # Webhooks may arrive out of order. Preserve the leave endpoint;
            # a later authenticated join event supplies the actual beginning.
            row = LearningAttendance(
                session_id=session.id,
                user_id=identity,
                participant_sid=sid,
                joined_at=occurred_at,
                left_at=occurred_at,
            )
            db.add(row)
        elif row.left_at is None or occurred_at > utc(row.left_at):
            row.left_at = occurred_at
        _attendance_seconds(row)


def _provider_recording(db, session, payload, occurred_at):
    if not session.recording_enabled:
        return
    data = payload.get("egressInfo") or {}
    egress_id = str(data.get("egressId", ""))
    if not egress_id or len(egress_id) > 128:
        return
    states = {
        0: "starting",
        1: "recording",
        2: "ending",
        3: "complete",
        4: "failed",
        5: "aborted",
        6: "limit",
    }
    try:
        state = states[int(data.get("status", 0))]
    except (ValueError, TypeError, KeyError):
        return
    recording = db.scalar(
        select(LearningRecording).where(LearningRecording.provider_egress_id == egress_id)
    )
    if recording is None:
        recording = LearningRecording(session_id=session.id, provider_egress_id=egress_id)
        db.add(recording)
    elif recording.session_id != session.id:
        raise EducationError("Provider recording belongs to another session.")
    terminal = {"complete", "failed", "aborted", "limit"}
    if recording.status in terminal:
        # Provider callbacks can arrive out of order. A late start/failure must
        # not rewrite a completed file, duration or completion timestamp.
        return
    phases = {"starting": 0, "recording": 1, "ending": 2}
    if state in phases and phases[state] < phases.get(recording.status, -1):
        return
    recording.status = state
    if recording.started_at is None and state in {"recording", "ending", "complete"}:
        recording.started_at = occurred_at
    if state in terminal:
        recording.completed_at = occurred_at
    for file in data.get("fileResults") or []:
        key = _recording_key(session.id, file.get("filename", ""))
        if key:
            recording.storage_key = key
            try:
                # LiveKit file durations are nanoseconds, not browser estimates.
                recording.duration_seconds = max(0, int(file.get("duration", 0)) // 1_000_000_000)
            except (ValueError, TypeError):
                recording.duration_seconds = 0
            break


def apply_provider_event(db, event_id, event_type, room_name, payload, occurred_at=None):
    """Apply an authenticated normalized LiveKit event exactly once.

    The caller verifies the signature over the raw body before invoking this
    internal hook. Its event ID and effects commit together. Unknown rooms are
    acknowledged without creating classroom state or attendance.
    """
    event_id, event_type = str(event_id or ""), str(event_type or "")
    if not event_id or len(event_id) > 128 or len(event_type) > 64 or not isinstance(payload, dict):
        raise EducationError("Invalid provider event.")
    payload_hash = hashlib.sha256(
        json.dumps(
            {"event_type": event_type, "room": room_name, "payload": payload},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    receipt = db.get(LearningWebhookReceipt, event_id)
    if receipt:
        if receipt.payload_hash != payload_hash:
            raise EducationError("This provider event ID has conflicting contents.", 409)
        return {"duplicate": True, "session_id": receipt.session_id}
    prefix = "nurse-learning-"
    if not str(room_name).startswith(prefix):
        return {"ignored": True}
    try:
        session_id = UUID(str(room_name)[len(prefix) :])
    except ValueError:
        return {"ignored": True}
    # Distinct provider event IDs may be delivered concurrently. Lock their
    # shared classroom row before claiming receipts so recording/attendance
    # evidence and terminal room states are serialized on PostgreSQL too.
    session = db.scalar(
        select(LearningSession)
        .where(LearningSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        return {"ignored": True}
    occurred_at = utc(occurred_at or datetime.now(UTC))
    if occurred_at > datetime.now(UTC) + timedelta(minutes=5):
        raise EducationError("The provider event timestamp is in the future.")
    db.add(
        LearningWebhookReceipt(
            provider_event_id=event_id,
            event_type=event_type,
            session_id=session.id,
            payload_hash=payload_hash,
            occurred_at=occurred_at,
        )
    )
    try:
        # Claim the receipt before updating evidence. A concurrent delivery waits
        # here and cannot apply attendance or recording effects a second time.
        db.flush()
    except IntegrityError:
        db.rollback()
        receipt = db.get(LearningWebhookReceipt, event_id)
        if receipt and receipt.payload_hash == payload_hash:
            return {"duplicate": True, "session_id": receipt.session_id}
        raise EducationError("Provider event receipt could not be saved.") from None
    # The receipt INSERT acquires SQLite's write lock. Refresh after that point
    # to avoid applying an earlier room snapshot over a committed terminal state.
    db.refresh(session)
    if event_type in {"participant_joined", "participant_left"}:
        _provider_attendance(db, session, event_type, payload, occurred_at)
    elif event_type == "room_started":
        if (
            session.status == "scheduled"
            and can_teach(db, db.get(User, session.educator_id))
            and (not session.course or session.course.status == "published")
            and utc(session.starts_at) - timedelta(minutes=15) <= occurred_at < utc(session.ends_at)
        ):
            session.status = "live"
    elif event_type == "room_finished":
        if session.status == "live":
            session.status = "ended"
        for row in db.scalars(
            select(LearningAttendance).where(
                LearningAttendance.session_id == session.id, LearningAttendance.left_at.is_(None)
            )
        ):
            row.left_at = occurred_at
            _attendance_seconds(row)
    elif event_type in {"egress_started", "egress_updated", "egress_ended"}:
        _provider_recording(db, session, payload, occurred_at)
    db.commit()
    return {"duplicate": False, "session_id": session.id}


def handle_live_webhook(db, event):
    """Compatibility adapter for a provider-verified normalized event dictionary."""
    return apply_provider_event(db, **event)


def attendance_summary(db, user, session_id):
    """Own provider-confirmed connected intervals, with overlapping tabs counted once."""
    session, _, host = _participant(db, user, session_id)
    query = select(LearningAttendance).where(LearningAttendance.session_id == session.id)
    if not host:
        query = query.where(LearningAttendance.user_id == user.id)
    rows = list(db.scalars(query.order_by(LearningAttendance.joined_at)))
    intervals = sorted(
        (utc(row.joined_at), utc(row.left_at))
        for row in rows
        if row.left_at and utc(row.left_at) >= utc(row.joined_at)
    )
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return {
        "records": rows,
        "seconds": sum(int((end - start).total_seconds()) for start, end in merged),
        "connected": any(row.left_at is None for row in rows),
        "basis": "provider-confirmed",
    }
