"""HTTP pages and authoring forms for courses, educators and live lectures.

Routes adapt browser input to the education domain; the domain owns validation,
ownership, seat accounting and progress. Every mutation requires a current
account and CSRF protection. Provider calls are confined to classroom routes.
Ordinary forms keep working without JavaScript, and validation failures retain
the submitted values. No route automatically approves an educator or publishes
invented content. See docs/LIVE_LEARNING_ARCHITECTURE.md for the route map.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.models.education import (
    LearningSession,
    QuizAttempt,
    QuizQuestion,
)
from app.models.user import User
from app.services import education
from app.web.deps import get_current_user, require_staff, require_user, verify_csrf
from app.web.education_common import (
    PREFIX,
    course_context,
    form_values,
    learning_page,
    lesson_context,
    managed_course,
    managed_module,
    session_context,
    teaching_profile,
)
from app.web.feedback import message, redirect_feedback, render_error

router = APIRouter(tags=["education"])
COURSE_FIELDS = ("title", "summary", "description", "category", "level")
LESSON_FIELDS = (
    "title",
    "kind",
    "content",
    "resource_url",
    "duration_minutes",
    "position",
    "pass_percentage",
)
SESSION_FIELDS = (
    "title",
    "description",
    "objectives",
    "course_id",
    "starts_at",
    "ends_at",
    "timezone",
    "session_format",
    "capacity",
    "chat_enabled",
    "recording_enabled",
    "status",
)


def saved(request, path, title, body):
    """Use the app's established redirect/JSON feedback contract after commit."""
    return redirect_feedback(request, path, message(title, body))


def rejected(request, template, user, values, error, **context):
    """Preserve editable input while exposing only the domain's safe error text."""
    return render_error(
        request,
        "education/" + template + ".html",
        {
            "user": user,
            "values": values,
            "title": "Learning",
            **context,
        },
        message("Please check these details", str(error), tone="error"),
        status_code=getattr(error, "status_code", 400),
    )


def _close_educator_classrooms(db, actor, educator_id):
    """Close every live room before removing its educator's publishing approval.

    The caller holds the educator lock and commits the resulting ended states
    with its profile change. Provider calls cannot share that transaction: if a
    later close fails, earlier rooms may already be disconnected. Database state
    rolls back, and the provider's idempotent delete makes retrying safe.
    """
    from app.web.education_classroom_routes import _transition

    session_ids = list(
        db.scalars(
            select(LearningSession.id)
            .where(
                LearningSession.educator_id == educator_id,
                LearningSession.status == "live",
            )
            .order_by(LearningSession.id)
        )
    )
    for session_id in session_ids:
        _transition(db, actor, session_id, "ended", commit=False)


def _apply_educator(db, user, values):
    """Validate first, then close existing media before a changed identity needs review."""
    from app.web.education_classroom_routes import _lock_educator

    _lock_educator(db, user.id)
    try:
        if education.educator_application_requires_review(db, user, values):
            _close_educator_classrooms(db, user, user.id)
        result = education.apply_educator(db, user, values, commit=False)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def _review_educator(db, staff, user_id, status, notes):
    """Keep approval intact until every active classroom accepts provider closure."""
    from app.web.education_classroom_routes import _lock_educator

    _lock_educator(db, user_id)
    try:
        _, notes = education.validate_educator_review(db, staff, user_id, status, notes)
        if status in {"paused", "rejected"}:
            _close_educator_classrooms(db, staff, user_id)
        result = education.review_educator(db, staff, user_id, status, notes, commit=False)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get(PREFIX)
def catalog(
    request: Request,
    q: str = Query("", max_length=120),
    category: str = Query("", max_length=100),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Public discovery lists only currently published, approved-educator learning."""
    courses = education.list_courses(db, user=user)
    categories = sorted({course.category for course in courses})
    if category:
        courses = [course for course in courses if course.category == category]
    sessions = education.list_sessions(db, user=user)
    if q:
        search = q.casefold()
        courses = [
            course
            for course in courses
            if search in (course.title + " " + course.summary + " " + course.category).casefold()
        ]
        sessions = [
            session
            for session in sessions
            if search in (session.title + " " + session.description).casefold()
        ]
    return learning_page(
        request,
        "catalog",
        user,
        courses=courses,
        sessions=sessions,
        educator=teaching_profile(db, user),
        categories=categories,
        search_query=q,
        category=category,
    )


@router.get(PREFIX + "/mine")
def my_learning(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Show this learner's courses, current progress and session reservations."""
    enrollments = education.my_enrollments(db, user)
    progress = {}
    available = []
    for item in enrollments:
        try:
            progress[item.course_id] = education.course_progress(db, user, item.course_id)
            available.append(item)
        except education.EducationError as error:
            if error.status_code not in {403, 404}:
                raise
    return learning_page(
        request,
        "mine",
        user,
        enrollments=available,
        unavailable_course_count=len(enrollments) - len(available),
        progress_by_course=progress,
        registrations=education.session_registrations(db, user),
    )


@router.get(PREFIX + "/studio")
def studio(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Private author workspace; the application state controls available actions."""
    return learning_page(
        request,
        "studio",
        user,
        educator=teaching_profile(db, user),
        courses=education.list_courses(db, user=user, owned=True),
        sessions=education.list_sessions(db, user=user, owned=True),
    )


@router.get(PREFIX + "/educator")
def educator_form(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Let a member explicitly choose a public teaching identity and biography."""
    profile = teaching_profile(db, user)
    values = (
        form_values(profile, ("display_name", "headline", "bio", "subjects")) if profile else {}
    )
    return learning_page(
        request,
        "educator_form",
        user,
        educator=profile,
        values=values,
        action_url=PREFIX + "/educator",
    )


@router.post(PREFIX + "/educator", dependencies=[Depends(verify_csrf)])
async def apply_educator(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Save an application without changing account type or staff authorization."""
    values = dict(await request.form())
    try:
        await run_in_threadpool(_apply_educator, db, user, values)
    except education.EducationError as error:
        return rejected(
            request,
            "educator_form",
            user,
            values,
            error,
            educator=teaching_profile(db, user),
            action_url=PREFIX + "/educator",
        )
    return saved(
        request,
        PREFIX + "/studio",
        "Educator application saved",
        "Your teaching profile is saved. Its current review status appears in your studio.",
    )


@router.get("/staff/educators")
def educator_review(
    request: Request,
    status: str = Query("", max_length=20),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Staff see applications and review notes; ordinary members cannot browse them."""
    rows = education.list_educators(db, pending=True, user=user)
    if status and status != "all":
        rows = [row for row in rows if row.status == status]
    return learning_page(request, "educator_review", user, educators=rows, status_filter=status)


@router.post("/staff/educators/{user_id}/review", dependencies=[Depends(verify_csrf)])
async def review_educator(
    user_id: UUID,
    request: Request,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Record a review decision through the domain's auditable approval boundary."""
    values = dict(await request.form())
    await run_in_threadpool(
        _review_educator,
        db,
        user,
        user_id,
        values.get("status", ""),
        values.get("notes", ""),
    )
    return saved(
        request,
        "/staff/educators",
        "Educator review saved",
        "The educator's current hosting permission has been updated.",
    )


@router.get(PREFIX + "/courses/new")
def new_course(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Create a draft only after educator approval; staff permission alone is insufficient."""
    if not education.can_teach(db, user):
        return saved(
            request,
            PREFIX + "/studio",
            "Teaching approval required",
            "Apply for educator hosting permission from your studio.",
        )
    return learning_page(request, "course_form", user, course=None, action_url=PREFIX + "/courses")


@router.post(PREFIX + "/courses", dependencies=[Depends(verify_csrf)])
async def create_course(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Persist a private course draft, retaining metadata on validation failure."""
    values = dict(await request.form())
    try:
        course = education.create_course(db, user, values)
    except education.EducationError as error:
        return rejected(
            request, "course_form", user, values, error, course=None, action_url=PREFIX + "/courses"
        )
    return saved(
        request,
        f"{PREFIX}/courses/{course.id}",
        "Course draft created",
        "Build the outline and lessons before publishing your course.",
    )


@router.get(PREFIX + "/courses/{course_id}")
def course_detail(
    course_id: UUID,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Public outline or private author preview; enrollment gates the actual lessons."""
    course = education.get_course(db, course_id, user=user)
    return learning_page(request, "course", user, **course_context(db, course, user))


@router.get(PREFIX + "/courses/{course_id}/edit")
def edit_course(
    course_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Authorize ownership before showing editable draft or published metadata."""
    course = managed_course(db, user, course_id)
    return learning_page(
        request,
        "course_form",
        user,
        course=course,
        values=form_values(course, COURSE_FIELDS),
        action_url=f"{PREFIX}/courses/{course.id}/edit",
    )


@router.post(PREFIX + "/courses/{course_id}/edit", dependencies=[Depends(verify_csrf)])
async def update_course(
    course_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Save author metadata without accepting ownership/status fields from the browser."""
    course = managed_course(db, user, course_id)
    values = dict(await request.form())
    try:
        education.update_course(db, user, course_id, values)
    except education.EducationError as error:
        return rejected(
            request,
            "course_form",
            user,
            values,
            error,
            course=course,
            action_url=f"{PREFIX}/courses/{course.id}/edit",
        )
    return saved(
        request,
        f"{PREFIX}/courses/{course.id}",
        "Course updated",
        "Your course details have been saved.",
    )


@router.post(PREFIX + "/courses/{course_id}/status", dependencies=[Depends(verify_csrf)])
async def course_status(
    course_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Publishing requires a usable outline; the domain checks that prerequisite."""
    values = dict(await request.form())
    education.set_course_status(db, user, course_id, values.get("status", ""))
    return saved(
        request,
        f"{PREFIX}/courses/{course_id}",
        "Course visibility updated",
        "Your course now has the selected publication status.",
    )


@router.post(PREFIX + "/courses/{course_id}/enroll", dependencies=[Depends(verify_csrf)])
def enroll_course(
    course_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Idempotently enroll the current account; learner identity is never form input."""
    education.enroll(db, user, course_id)
    return saved(
        request,
        f"{PREFIX}/courses/{course_id}",
        "You are enrolled",
        "Open the course outline to begin learning.",
    )


@router.get(PREFIX + "/courses/{course_id}/modules/new")
def new_module(
    course_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Show a new module form only to this course's authorized editor."""
    course = managed_course(db, user, course_id)
    next_position = (
        max((module.position for module in course_context(db, course, user)["modules"]), default=0)
        + 1
    )
    return learning_page(
        request,
        "module_form",
        user,
        course=course,
        module=None,
        values={"position": next_position},
        action_url=f"{PREFIX}/courses/{course_id}/modules",
    )


@router.post(PREFIX + "/courses/{course_id}/modules", dependencies=[Depends(verify_csrf)])
async def create_module(
    course_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Append an ordered module, reporting conflicting positions without losing input."""
    course = managed_course(db, user, course_id)
    values = dict(await request.form())
    try:
        education.save_module(db, user, course_id, values)
    except education.EducationError as error:
        return rejected(
            request,
            "module_form",
            user,
            values,
            error,
            course=course,
            module=None,
            action_url=f"{PREFIX}/courses/{course_id}/modules",
        )
    return saved(
        request,
        f"{PREFIX}/courses/{course_id}",
        "Module added",
        "Add focused lessons to this part of your course.",
    )


@router.get(PREFIX + "/modules/{module_id}/edit")
def edit_module(
    module_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Resolve module ownership through the parent course."""
    module, course = managed_module(db, user, module_id)
    return learning_page(
        request,
        "module_form",
        user,
        course=course,
        module=module,
        values=form_values(module, ("title", "position")),
        action_url=f"{PREFIX}/modules/{module_id}/edit",
    )


@router.post(PREFIX + "/modules/{module_id}/edit", dependencies=[Depends(verify_csrf)])
async def update_module(
    module_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Keep parent ownership fixed while editing a module's title/order."""
    module, course = managed_module(db, user, module_id)
    values = dict(await request.form())
    try:
        education.save_module(db, user, course.id, values, module_id=module_id)
    except education.EducationError as error:
        return rejected(
            request,
            "module_form",
            user,
            values,
            error,
            course=course,
            module=module,
            action_url=f"{PREFIX}/modules/{module_id}/edit",
        )
    return saved(
        request,
        f"{PREFIX}/courses/{course.id}",
        "Module updated",
        "Your module title and position have been saved.",
    )


@router.get(PREFIX + "/modules/{module_id}/lessons/new")
def new_lesson(
    module_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Prepare a lesson inside an authorized module."""
    module, course = managed_module(db, user, module_id)
    next_position = (
        max(
            (
                lesson.position
                for lesson in course_context(db, course, user)["lessons_by_module"][module_id]
            ),
            default=0,
        )
        + 1
    )
    return learning_page(
        request,
        "lesson_form",
        user,
        module=module,
        course=course,
        lesson=None,
        values={"position": next_position},
        action_url=f"{PREFIX}/modules/{module_id}/lessons",
    )


@router.post(PREFIX + "/modules/{module_id}/lessons", dependencies=[Depends(verify_csrf)])
async def create_lesson(
    module_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Validate text/resource/video/quiz content through the domain service."""
    module, course = managed_module(db, user, module_id)
    values = dict(await request.form())
    try:
        lesson = education.save_lesson(db, user, module_id, values)
    except education.EducationError as error:
        return rejected(
            request,
            "lesson_form",
            user,
            values,
            error,
            module=module,
            course=course,
            lesson=None,
            action_url=f"{PREFIX}/modules/{module_id}/lessons",
        )
    return saved(
        request,
        f"{PREFIX}/lessons/{lesson.id}/edit",
        "Lesson added",
        "Your lesson is saved. Add knowledge-check questions here when appropriate.",
    )


@router.get(PREFIX + "/lessons/{lesson_id}/edit")
def edit_lesson(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Answer keys are requested explicitly only after author ownership is checked."""
    context = lesson_context(db, user, lesson_id)
    managed_course(db, user, context["course"].id)
    lesson = context["lesson"]
    questions = (
        education.quiz_questions(db, user, lesson_id, include_answers=True)
        if lesson.kind == "quiz"
        else []
    )
    context.pop("quiz_questions", None)
    return learning_page(
        request,
        "lesson_form",
        user,
        **context,
        quiz_questions=questions,
        values=form_values(lesson, LESSON_FIELDS),
        action_url=f"{PREFIX}/lessons/{lesson_id}/edit",
    )


@router.post(PREFIX + "/lessons/{lesson_id}/edit", dependencies=[Depends(verify_csrf)])
async def update_lesson(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Edit only within the existing parent module; preserve values on validation errors."""
    context = lesson_context(db, user, lesson_id)
    managed_course(db, user, context["course"].id)
    values = dict(await request.form())
    try:
        education.save_lesson(db, user, context["module"].id, values, lesson_id=lesson_id)
    except education.EducationError as error:
        return rejected(
            request,
            "lesson_form",
            user,
            values,
            error,
            **context,
            action_url=f"{PREFIX}/lessons/{lesson_id}/edit",
        )
    return saved(
        request,
        f"{PREFIX}/courses/{context['course'].id}",
        "Lesson updated",
        "Your teaching content has been saved.",
    )


@router.post(PREFIX + "/lessons/{lesson_id}/questions", dependencies=[Depends(verify_csrf)])
async def add_question(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Author quiz answer keys through an owner-only endpoint."""
    values = dict(await request.form())
    education.save_quiz_question(db, user, lesson_id, values)
    return saved(
        request,
        f"{PREFIX}/lessons/{lesson_id}/edit",
        "Question added",
        "The knowledge check now includes your question and explanation.",
    )


@router.post(PREFIX + "/questions/{question_id}/edit", dependencies=[Depends(verify_csrf)])
async def edit_question(
    question_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Update an owned answer key; the domain invalidates obsolete passing progress."""
    question = db.get(QuizQuestion, question_id)
    if question is None:
        raise education.EducationError("This knowledge-check question is unavailable.", 404)
    values = dict(await request.form())
    education.save_quiz_question(db, user, question.lesson_id, values, question_id=question_id)
    return saved(
        request,
        f"{PREFIX}/lessons/{question.lesson_id}/edit",
        "Question updated",
        "Your revised knowledge check has been saved.",
    )


@router.post(PREFIX + "/questions/{question_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_question(
    question_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Delete only through course ownership checks, then return to the lesson editor."""
    question = db.get(QuizQuestion, question_id)
    if question is None:
        raise education.EducationError("This knowledge-check question is unavailable.", 404)
    lesson_id = question.lesson_id
    education.delete_learning_item(db, user, "question", question_id)
    return saved(
        request,
        f"{PREFIX}/lessons/{lesson_id}/edit",
        "Question removed",
        "The course's progress now reflects its current knowledge check.",
    )


@router.post(PREFIX + "/lessons/{lesson_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_lesson(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Remove an owned lesson and its dependent progress through the domain."""
    context = lesson_context(db, user, lesson_id)
    course_id = context["course"].id
    education.delete_learning_item(db, user, "lesson", lesson_id)
    return saved(
        request,
        f"{PREFIX}/courses/{course_id}",
        "Lesson removed",
        "The course outline and learner progress reflect this change.",
    )


@router.post(PREFIX + "/modules/{module_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_module(
    module_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Remove an owned module with its lessons; the educator confirms this in the form."""
    module, course = managed_module(db, user, module_id)
    education.delete_learning_item(db, user, "module", module.id)
    return saved(
        request,
        f"{PREFIX}/courses/{course.id}",
        "Module removed",
        "The course outline now contains the remaining modules.",
    )


@router.get(PREFIX + "/lessons/{lesson_id}")
def lesson_reader(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Show current-revision results and safe feedback with a fresh attempt key.

    Old attempts remain in the learning history but cannot claim that a revised
    knowledge check is complete. The domain exposes explanations only after
    verifying this learner owns the scored attempt.
    """
    context = lesson_context(db, user, lesson_id)
    attempt = db.scalar(
        select(QuizAttempt)
        .where(
            QuizAttempt.lesson_id == lesson_id,
            QuizAttempt.user_id == user.id,
            QuizAttempt.lesson_revision == context["lesson"].revision,
        )
        .order_by(QuizAttempt.created_at.desc())
        .limit(1)
    )
    result = (
        {
            "score": round(attempt.score * 100 / attempt.total),
            "passed": attempt.passed,
            "feedback": education.quiz_attempt_feedback(db, user, attempt),
        }
        if attempt
        else None
    )
    return learning_page(
        request, "lesson", user, **context, quiz_result=result, request_id=str(uuid4())
    )


@router.post(PREFIX + "/lessons/{lesson_id}/complete", dependencies=[Depends(verify_csrf)])
def complete_lesson(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Record this learner's acknowledgment; quizzes require a server-scored pass."""
    education.mark_lesson_complete(db, user, lesson_id)
    return saved(
        request,
        f"{PREFIX}/lessons/{lesson_id}",
        "Progress saved",
        "This lesson is complete in your learning record.",
    )


@router.post(PREFIX + "/lessons/{lesson_id}/quiz", dependencies=[Depends(verify_csrf)])
async def submit_quiz(
    lesson_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Score the displayed revision; retries reuse the original request key.

    Forwarding the hidden revision is required: an educator can change options
    while a learner has an old form open. The domain rejects that stale form
    rather than grading its option positions against the revised answer key.
    """
    values = dict(await request.form())
    if not values.get("lesson_revision"):
        raise education.EducationError("Refresh this lesson before submitting its quiz.")
    answers = {
        key.removeprefix("question_"): value
        for key, value in values.items()
        if key.startswith("question_")
    }
    attempt = education.submit_quiz(
        db,
        user,
        lesson_id,
        answers,
        request_id=values.get("request_id"),
        lesson_revision=values["lesson_revision"],
    )
    title = "Knowledge check completed" if attempt.passed else "Knowledge check saved"
    return saved(
        request,
        f"{PREFIX}/lessons/{lesson_id}",
        title,
        "Review your result and continue learning at your pace.",
    )


@router.get(PREFIX + "/sessions/new")
def new_session(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Scheduling is educator-only; normal staff permission does not grant hosting."""
    if not education.can_teach(db, user):
        return saved(
            request,
            PREFIX + "/studio",
            "Teaching approval required",
            "Apply for educator hosting permission from your studio.",
        )
    return learning_page(
        request,
        "session_form",
        user,
        session=None,
        courses=education.list_courses(db, user=user, owned=True),
        action_url=PREFIX + "/sessions",
    )


@router.post(PREFIX + "/sessions", dependencies=[Depends(verify_csrf)])
async def create_session(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Publish a schedule without creating a video room or pretending it is live."""
    values = dict(await request.form())
    values.setdefault("status", "scheduled")
    for field in ("chat_enabled", "recording_enabled"):
        values[field] = values.get(field, "false")
    try:
        session = education.create_session(db, user, values)
    except education.EducationError as error:
        return rejected(
            request,
            "session_form",
            user,
            values,
            error,
            session=None,
            courses=education.list_courses(db, user=user, owned=True),
            action_url=PREFIX + "/sessions",
        )
    return saved(
        request,
        f"{PREFIX}/sessions/{session.id}",
        "Lecture draft created" if session.status == "draft" else "Lecture scheduled",
        "Schedule this lecture when its timing and details are ready."
        if session.status == "draft"
        else "Learners can reserve a place and view the session details.",
    )


@router.get(PREFIX + "/sessions/{session_id}")
def session_detail(
    session_id: UUID,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Public lecture details include timing and recording notices, never an attendee list."""
    session = education.get_session(db, session_id, user=user)
    try:
        recordings = education.session_recordings(db, user, session_id) if user else []
    except education.EducationError:
        recordings = []
    complete = next((row for row in recordings if row.status == "complete"), None)
    active = next(
        (row for row in recordings if row.status in {"starting", "recording", "ending"}), None
    )
    return learning_page(
        request,
        "session",
        user,
        **session_context(db, session, user),
        recordings=recordings,
        active_recording=active,
        calendar_url=f"{PREFIX}/sessions/{session_id}/calendar.ics",
        recording_url=f"{PREFIX}/recordings/{complete.id}" if complete else "",
    )


@router.get(PREFIX + "/sessions/{session_id}/calendar.ics")
def lecture_calendar(
    session_id: UUID, user: User | None = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Reuse RFC 5545 escaping/folding for a public session's UTC calendar record."""
    from types import SimpleNamespace

    from fastapi.responses import Response

    from app.core.public_urls import public_url
    from app.services.events import calendar

    session = education.get_session(db, session_id, user=user)
    entry = SimpleNamespace(
        id=session.id,
        title=session.title,
        description=session.description + "\n\n" + public_url(f"{PREFIX}/sessions/{session_id}"),
        location="Nurse.ng online classroom",
        starts_at=session.starts_at,
        ends_at=session.ends_at,
        updated_at=session.updated_at,
        status=session.status,
    )
    return Response(
        calendar(entry),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="lecture-{session_id}.ics"',
            "Cache-Control": "no-store",
        },
    )


@router.post(PREFIX + "/sessions/{session_id}/status", dependencies=[Depends(verify_csrf)])
async def schedule_draft(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Publish a draft schedule without starting its remote media room."""
    values = dict(await request.form())
    if values.get("status") != "scheduled":
        raise education.EducationError("Choose Schedule to publish this lecture.")
    education.change_session_state(db, user, session_id, "scheduled")
    return saved(
        request,
        f"{PREFIX}/sessions/{session_id}",
        "Lecture scheduled",
        "Learners can now reserve a place in your lecture.",
    )


@router.get(PREFIX + "/sessions/{session_id}/edit")
def edit_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Show editable session fields only to its authorized owner or moderator."""
    session = education.get_session(db, session_id, user=user)
    if not session_context(db, session, user)["can_manage"]:
        from fastapi import HTTPException

        raise HTTPException(403, "Only this lecture's educator can edit it.")
    return learning_page(
        request,
        "session_form",
        user,
        session=session,
        courses=education.list_courses(db, user=user, owned=True),
        values=form_values(session, SESSION_FIELDS),
        action_url=f"{PREFIX}/sessions/{session_id}/edit",
    )


@router.post(PREFIX + "/sessions/{session_id}/edit", dependencies=[Depends(verify_csrf)])
async def update_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Changes to scheduled teaching stay within the original educator's ownership."""
    session = education.get_session(db, session_id, user=user)
    values = dict(await request.form())
    for field in ("chat_enabled", "recording_enabled"):
        values[field] = values.get(field, "false")
    try:
        education.update_session(db, user, session_id, values)
    except education.EducationError as error:
        return rejected(
            request,
            "session_form",
            user,
            values,
            error,
            session=session,
            courses=education.list_courses(db, user=user, owned=True),
            action_url=f"{PREFIX}/sessions/{session_id}/edit",
        )
    from app.models.education import SessionRegistration
    from app.services.education_notifications import notify_session_change

    recipients = db.scalars(
        select(SessionRegistration.user_id).where(
            SessionRegistration.session_id == session_id,
            SessionRegistration.status == "reserved",
        )
    ).all()
    notify_session_change(db, session, recipients, "updated")
    return saved(
        request,
        f"{PREFIX}/sessions/{session_id}",
        "Lecture updated",
        "The current session details have been saved.",
    )


@router.post(PREFIX + "/sessions/{session_id}/register", dependencies=[Depends(verify_csrf)])
def register_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Reserve a counted seat atomically; repeated requests reuse the reservation."""
    education.register_session(db, user, session_id)
    return saved(
        request,
        f"{PREFIX}/sessions/{session_id}",
        "Your place is reserved",
        "Find this lecture again in My learning.",
    )


@router.post(PREFIX + "/sessions/{session_id}/withdraw", dependencies=[Depends(verify_csrf)])
def withdraw_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Release this learner's reservation; the domain preserves moderation history."""
    education.cancel_registration(db, user, session_id)
    return saved(
        request,
        f"{PREFIX}/sessions/{session_id}",
        "Registration withdrawn",
        "Your reserved place has been released.",
    )
