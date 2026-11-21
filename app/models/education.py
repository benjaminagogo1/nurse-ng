"""Education records, hosting permissions, and evidence from the live provider.

Educator approval grants teaching permissions only; it never changes staff
permissions or asserts professional accreditation. Published courses contain
ordered modules and lessons. Enrollment and lesson progress belong to the
learner, while quiz answer keys remain server-side. Session reservations use a
separate counted seat allocation so the service can enforce capacity atomically.

Live attendance and recording metadata are written only after a provider webhook
has been authenticated. Reservations and self-reported lesson completion are not
attendance or accreditation evidence. Recording objects remain private.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EducatorProfile(TimestampMixin, Base):
    """A member's application and independently revocable hosting approval."""

    __tablename__ = "educator_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    headline: Mapped[str] = mapped_column(String(200))
    bio: Mapped[str] = mapped_column(Text)
    subjects: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", index=True
    )
    review_notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','paused','rejected')", name="educator_status_valid"
        ),
    )

    @property
    def id(self):
        """Expose a stable public identifier without introducing another identity."""
        return self.user_id


class EducatorReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Staff decision history; notes are visible to staff and the applicant."""

    __tablename__ = "educator_reviews"
    educator_id: Mapped[UUID] = mapped_column(
        ForeignKey("educator_profiles.user_id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    previous_status: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")


class LearningCourse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Educator-owned course; only published courses from active educators list publicly."""

    __tablename__ = "learning_courses"
    educator_id: Mapped[UUID] = mapped_column(
        ForeignKey("educator_profiles.user_id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    summary: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        String(100), default="General nursing", server_default="General nursing"
    )
    level: Mapped[str] = mapped_column(String(20), default="all", server_default="all")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", index=True
    )
    educator: Mapped[EducatorProfile] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','published','archived')", name="learning_course_status_valid"
        ),
        CheckConstraint(
            "level IN ('beginner','intermediate','advanced','all')",
            name="learning_course_level_valid",
        ),
    )


class LearningModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A course section with a unique positive position inside its owning course."""

    __tablename__ = "learning_modules"
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    position: Mapped[int] = mapped_column(Integer)
    course: Mapped[LearningCourse] = relationship()
    __table_args__ = (
        UniqueConstraint("course_id", "position", name="learning_module_order_unique"),
        CheckConstraint("position > 0", name="learning_module_position_positive"),
    )


class LearningLesson(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ordered content whose revision binds quiz forms and completion evidence.

    Changing teaching content or assessment rules advances the revision and
    invalidates affected completion in the service; historical attempts remain.
    """

    __tablename__ = "learning_lessons"
    module_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_modules.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(20), default="text", server_default="text")
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    resource_url: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    position: Mapped[int] = mapped_column(Integer)
    pass_percentage: Mapped[int] = mapped_column(Integer, default=70, server_default="70")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    module: Mapped[LearningModule] = relationship()
    __table_args__ = (
        UniqueConstraint("module_id", "position", name="learning_lesson_order_unique"),
        CheckConstraint(
            "kind IN ('text','resource','video','quiz')", name="learning_lesson_kind_valid"
        ),
        CheckConstraint(
            "position > 0 AND duration_minutes >= 0 AND duration_minutes <= 1440",
            name="learning_lesson_numbers_valid",
        ),
        CheckConstraint(
            "pass_percentage >= 1 AND pass_percentage <= 100", name="learning_lesson_pass_valid"
        ),
        CheckConstraint("revision >= 1", name="learning_lesson_revision_positive"),
    )


class LearningEnrollment(TimestampMixin, Base):
    """Course membership; completion is learning progress, not a clinical qualification."""

    __tablename__ = "learning_enrollments"
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_courses.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    course: Mapped[LearningCourse] = relationship()


class LessonProgress(TimestampMixin, Base):
    """One completion per learner/lesson, distinguished by reading or scored quiz."""

    __tablename__ = "learning_lesson_progress"
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_lessons.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completion_basis: Mapped[str] = mapped_column(
        String(20), default="self-reported", server_default="self-reported"
    )
    __table_args__ = (
        CheckConstraint(
            "completion_basis IN ('self-reported','quiz')", name="learning_completion_basis_valid"
        ),
    )


class QuizQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Answer keys are never included in learner question dictionaries."""

    __tablename__ = "learning_quiz_questions"
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_lessons.id", ondelete="CASCADE"), index=True
    )
    prompt: Mapped[str] = mapped_column(String(2000))
    options: Mapped[list] = mapped_column(JSON)
    correct_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text, default="", server_default="")
    position: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("lesson_id", "position", name="learning_quiz_order_unique"),
        CheckConstraint(
            "position > 0 AND correct_index >= 0 AND correct_index <= 5",
            name="learning_quiz_numbers_valid",
        ),
    )


class QuizAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A learner's scored submission at one revision, with an idempotent request ID.

    Stored answers are the learner's choices. Private correct indices remain on
    QuizQuestion, and feedback is authorized separately from this historical row.
    """

    __tablename__ = "learning_quiz_attempts"
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_lessons.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    lesson_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    answers: Mapped[dict] = mapped_column(JSON)
    score: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    __table_args__ = (
        UniqueConstraint("lesson_id", "user_id", "request_id", name="learning_quiz_request_unique"),
        CheckConstraint(
            "score >= 0 AND total > 0 AND score <= total", name="learning_quiz_score_valid"
        ),
        CheckConstraint("lesson_revision >= 1", name="learning_quiz_revision_positive"),
    )


class LearningSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Scheduled classroom and seat counter; provider state is tracked separately."""

    __tablename__ = "learning_sessions"
    educator_id: Mapped[UUID] = mapped_column(
        ForeignKey("educator_profiles.user_id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_courses.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    objectives: Mapped[str] = mapped_column(Text, default="", server_default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(
        String(64), default="Africa/Lagos", server_default="Africa/Lagos"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", index=True
    )
    session_format: Mapped[str] = mapped_column(
        String(20), default="lecture", server_default="lecture"
    )
    capacity: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    reserved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    chat_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    educator: Mapped[EducatorProfile] = relationship()
    course: Mapped[LearningCourse | None] = relationship()
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','live','ended','cancelled')",
            name="learning_session_status_valid",
        ),
        CheckConstraint(
            "session_format IN ('lecture','discussion')", name="learning_session_format_valid"
        ),
        CheckConstraint("ends_at > starts_at", name="learning_session_time_order"),
        CheckConstraint(
            "capacity >= 1 AND capacity <= 1000 "
            "AND reserved_count >= 0 AND reserved_count <= capacity",
            name="learning_session_capacity_valid",
        ),
    )


class SessionRegistration(TimestampMixin, Base):
    """One learner's seat and authoritative speaking/removal state for a session.

    Reconnection uses speaker_allowed rather than reconstructing default rights
    from lecture/discussion mode. Removed reservations cannot reserve again.
    """

    __tablename__ = "learning_session_registrations"
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), default="reserved", server_default="reserved")
    speaker_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    hand_raised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session: Mapped[LearningSession] = relationship()
    __table_args__ = (
        CheckConstraint(
            "status IN ('reserved','cancelled','removed')",
            name="learning_registration_status_valid",
        ),
    )


class SessionMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Plain-text participant discussion with host-controlled visibility and answers."""

    __tablename__ = "learning_session_messages"
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), default="question", server_default="question")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="visible", server_default="visible")
    answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    answered_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("kind IN ('question','chat')", name="learning_message_kind_valid"),
        CheckConstraint("status IN ('visible','hidden')", name="learning_message_status_valid"),
    )


class SessionModeration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit history for lifecycle, message and participant moderation actions."""

    __tablename__ = "learning_session_moderation"
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))


class LearningAttendance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One provider connection; reconnects produce distinct records and durations."""

    __tablename__ = "learning_attendance"
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    participant_sid: Mapped[str] = mapped_column(String(128))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (
        UniqueConstraint(
            "session_id", "participant_sid", name="learning_attendance_connection_unique"
        ),
        CheckConstraint("seconds >= 0", name="learning_attendance_seconds_valid"),
    )


class LearningRecording(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Private provider object metadata; access is authorized at playback time."""

    __tablename__ = "learning_recordings"
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    provider_egress_id: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="starting", server_default="starting")
    storage_key: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('starting','recording','ending','complete','failed','aborted','limit')",
            name="learning_recording_status_valid",
        ),
        CheckConstraint("duration_seconds >= 0", name="learning_recording_duration_valid"),
    )


class LearningWebhookReceipt(TimestampMixin, Base):
    """Replay evidence and provider timestamps without storing raw webhook payloads."""

    __tablename__ = "learning_webhook_receipts"
    provider_event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="SET NULL")
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
