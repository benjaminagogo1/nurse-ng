"""Add educator courses and live learning classrooms

Revision ID: e6480k1e9038
Revises: e6480j0f6527
Create Date: 2026-11-20 23:23:39.440138

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e6480k1e9038'
down_revision: str | None = 'e6480j0f6527'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add education records without seeding members, approval or attendance."""
    op.create_table('educator_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('headline', sa.String(length=200), nullable=False),
    sa.Column('bio', sa.Text(), nullable=False),
    sa.Column('subjects', sa.String(length=500), server_default='', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('review_notes', sa.Text(), server_default='', nullable=False),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('pending','approved','paused','rejected')", name='educator_status_valid'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_educator_profiles_created_at'), 'educator_profiles', ['created_at'], unique=False)
    op.create_index(op.f('ix_educator_profiles_status'), 'educator_profiles', ['status'], unique=False)
    op.create_table('educator_reviews',
    sa.Column('educator_id', sa.Uuid(), nullable=False),
    sa.Column('reviewer_id', sa.Uuid(), nullable=True),
    sa.Column('previous_status', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['educator_id'], ['educator_profiles.user_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_educator_reviews_created_at'), 'educator_reviews', ['created_at'], unique=False)
    op.create_index(op.f('ix_educator_reviews_educator_id'), 'educator_reviews', ['educator_id'], unique=False)
    op.create_table('learning_courses',
    sa.Column('educator_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=100), server_default='General nursing', nullable=False),
    sa.Column('level', sa.String(length=20), server_default='all', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("level IN ('beginner','intermediate','advanced','all')", name='learning_course_level_valid'),
    sa.CheckConstraint("status IN ('draft','published','archived')", name='learning_course_status_valid'),
    sa.ForeignKeyConstraint(['educator_id'], ['educator_profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_learning_courses_created_at'), 'learning_courses', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_courses_educator_id'), 'learning_courses', ['educator_id'], unique=False)
    op.create_index(op.f('ix_learning_courses_status'), 'learning_courses', ['status'], unique=False)
    op.create_table('learning_enrollments',
    sa.Column('course_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['learning_courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('course_id', 'user_id')
    )
    op.create_index(op.f('ix_learning_enrollments_created_at'), 'learning_enrollments', ['created_at'], unique=False)
    op.create_table('learning_modules',
    sa.Column('course_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('position > 0', name='learning_module_position_positive'),
    sa.ForeignKeyConstraint(['course_id'], ['learning_courses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('course_id', 'position', name='learning_module_order_unique')
    )
    op.create_index(op.f('ix_learning_modules_course_id'), 'learning_modules', ['course_id'], unique=False)
    op.create_index(op.f('ix_learning_modules_created_at'), 'learning_modules', ['created_at'], unique=False)
    op.create_table('learning_sessions',
    sa.Column('educator_id', sa.Uuid(), nullable=False),
    sa.Column('course_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('objectives', sa.Text(), server_default='', nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='Africa/Lagos', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('session_format', sa.String(length=20), server_default='lecture', nullable=False),
    sa.Column('capacity', sa.Integer(), server_default='50', nullable=False),
    sa.Column('reserved_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('recording_enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('chat_enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("session_format IN ('lecture','discussion')", name='learning_session_format_valid'),
    sa.CheckConstraint("status IN ('draft','scheduled','live','ended','cancelled')", name='learning_session_status_valid'),
    sa.CheckConstraint('capacity >= 1 AND capacity <= 1000 AND reserved_count >= 0 AND reserved_count <= capacity', name='learning_session_capacity_valid'),
    sa.CheckConstraint('ends_at > starts_at', name='learning_session_time_order'),
    sa.ForeignKeyConstraint(['course_id'], ['learning_courses.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['educator_id'], ['educator_profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_learning_sessions_course_id'), 'learning_sessions', ['course_id'], unique=False)
    op.create_index(op.f('ix_learning_sessions_created_at'), 'learning_sessions', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_sessions_educator_id'), 'learning_sessions', ['educator_id'], unique=False)
    op.create_index(op.f('ix_learning_sessions_starts_at'), 'learning_sessions', ['starts_at'], unique=False)
    op.create_index(op.f('ix_learning_sessions_status'), 'learning_sessions', ['status'], unique=False)
    op.create_table('learning_attendance',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('participant_sid', sa.String(length=128), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('seconds', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('seconds >= 0', name='learning_attendance_seconds_valid'),
    sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'participant_sid', name='learning_attendance_connection_unique')
    )
    op.create_index(op.f('ix_learning_attendance_created_at'), 'learning_attendance', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_attendance_session_id'), 'learning_attendance', ['session_id'], unique=False)
    op.create_index(op.f('ix_learning_attendance_user_id'), 'learning_attendance', ['user_id'], unique=False)
    op.create_table('learning_lessons',
    sa.Column('module_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('kind', sa.String(length=20), server_default='text', nullable=False),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('resource_url', sa.String(length=2048), server_default='', nullable=False),
    sa.Column('duration_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('pass_percentage', sa.Integer(), server_default='70', nullable=False),
    sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("kind IN ('text','resource','video','quiz')", name='learning_lesson_kind_valid'),
    sa.CheckConstraint('pass_percentage >= 1 AND pass_percentage <= 100', name='learning_lesson_pass_valid'),
    sa.CheckConstraint('revision >= 1', name='learning_lesson_revision_positive'),
    sa.CheckConstraint('position > 0 AND duration_minutes >= 0 AND duration_minutes <= 1440', name='learning_lesson_numbers_valid'),
    sa.ForeignKeyConstraint(['module_id'], ['learning_modules.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('module_id', 'position', name='learning_lesson_order_unique')
    )
    op.create_index(op.f('ix_learning_lessons_created_at'), 'learning_lessons', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_lessons_module_id'), 'learning_lessons', ['module_id'], unique=False)
    op.create_table('learning_recordings',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('provider_egress_id', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='starting', nullable=False),
    sa.Column('storage_key', sa.String(length=2048), server_default='', nullable=False),
    sa.Column('duration_seconds', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('starting','recording','ending','complete','failed','aborted','limit')", name='learning_recording_status_valid'),
    sa.CheckConstraint('duration_seconds >= 0', name='learning_recording_duration_valid'),
    sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_egress_id')
    )
    op.create_index(op.f('ix_learning_recordings_created_at'), 'learning_recordings', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_recordings_session_id'), 'learning_recordings', ['session_id'], unique=False)
    op.create_table('learning_session_messages',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=20), server_default='question', nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='visible', nullable=False),
    sa.Column('answer', sa.Text(), server_default='', nullable=False),
    sa.Column('answered_by', sa.Uuid(), nullable=True),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("kind IN ('question','chat')", name='learning_message_kind_valid'),
    sa.CheckConstraint("status IN ('visible','hidden')", name='learning_message_status_valid'),
    sa.ForeignKeyConstraint(['answered_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_learning_session_messages_created_at'), 'learning_session_messages', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_session_messages_session_id'), 'learning_session_messages', ['session_id'], unique=False)
    op.create_table('learning_session_moderation',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('target_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_learning_session_moderation_created_at'), 'learning_session_moderation', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_session_moderation_session_id'), 'learning_session_moderation', ['session_id'], unique=False)
    op.create_table('learning_session_registrations',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='reserved', nullable=False),
    sa.Column('speaker_allowed', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('hand_raised_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('reserved','cancelled','removed')", name='learning_registration_status_valid'),
    sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('session_id', 'user_id')
    )
    op.create_index(op.f('ix_learning_session_registrations_created_at'), 'learning_session_registrations', ['created_at'], unique=False)
    op.create_table('learning_webhook_receipts',
    sa.Column('provider_event_id', sa.String(length=128), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('provider_event_id')
    )
    op.create_index(op.f('ix_learning_webhook_receipts_created_at'), 'learning_webhook_receipts', ['created_at'], unique=False)
    op.create_table('learning_lesson_progress',
    sa.Column('lesson_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completion_basis', sa.String(length=20), server_default='self-reported', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("completion_basis IN ('self-reported','quiz')", name='learning_completion_basis_valid'),
    sa.ForeignKeyConstraint(['lesson_id'], ['learning_lessons.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('lesson_id', 'user_id')
    )
    op.create_index(op.f('ix_learning_lesson_progress_created_at'), 'learning_lesson_progress', ['created_at'], unique=False)
    op.create_table('learning_quiz_attempts',
    sa.Column('lesson_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('lesson_revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('answers', sa.JSON(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('passed', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('score >= 0 AND total > 0 AND score <= total', name='learning_quiz_score_valid'),
    sa.CheckConstraint('lesson_revision >= 1', name='learning_quiz_revision_positive'),
    sa.ForeignKeyConstraint(['lesson_id'], ['learning_lessons.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lesson_id', 'user_id', 'request_id', name='learning_quiz_request_unique')
    )
    op.create_index(op.f('ix_learning_quiz_attempts_created_at'), 'learning_quiz_attempts', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_quiz_attempts_lesson_id'), 'learning_quiz_attempts', ['lesson_id'], unique=False)
    op.create_index(op.f('ix_learning_quiz_attempts_user_id'), 'learning_quiz_attempts', ['user_id'], unique=False)
    op.create_table('learning_quiz_questions',
    sa.Column('lesson_id', sa.Uuid(), nullable=False),
    sa.Column('prompt', sa.String(length=2000), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('correct_index', sa.Integer(), nullable=False),
    sa.Column('explanation', sa.Text(), server_default='', nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('position > 0 AND correct_index >= 0 AND correct_index <= 5', name='learning_quiz_numbers_valid'),
    sa.ForeignKeyConstraint(['lesson_id'], ['learning_lessons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lesson_id', 'position', name='learning_quiz_order_unique')
    )
    op.create_index(op.f('ix_learning_quiz_questions_created_at'), 'learning_quiz_questions', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_quiz_questions_lesson_id'), 'learning_quiz_questions', ['lesson_id'], unique=False)
    # SQLite cannot add foreign keys with ALTER TABLE. Batch recreation preserves
    # existing notification rows and constraints on both supported databases.
    with op.batch_alter_table('notifications') as batch:
        batch.add_column(sa.Column('learning_session_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_notifications_learning_session', 'learning_sessions', ['learning_session_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_notifications_learning_session_id'), 'notifications', ['learning_session_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Remove the empty schema only; existing education records require export first."""
    connection = op.get_bind()
    for table in ('educator_profiles', 'learning_courses', 'learning_sessions'):
        if connection.execute(sa.text(f'SELECT count(*) FROM {table}')).scalar_one():
            raise RuntimeError('Education data exists; export it before downgrading.')
    op.drop_index(op.f('ix_notifications_learning_session_id'), table_name='notifications')
    with op.batch_alter_table('notifications') as batch:
        batch.drop_constraint('fk_notifications_learning_session', type_='foreignkey')
        batch.drop_column('learning_session_id')
    op.drop_index(op.f('ix_learning_quiz_questions_lesson_id'), table_name='learning_quiz_questions')
    op.drop_index(op.f('ix_learning_quiz_questions_created_at'), table_name='learning_quiz_questions')
    op.drop_table('learning_quiz_questions')
    op.drop_index(op.f('ix_learning_quiz_attempts_user_id'), table_name='learning_quiz_attempts')
    op.drop_index(op.f('ix_learning_quiz_attempts_lesson_id'), table_name='learning_quiz_attempts')
    op.drop_index(op.f('ix_learning_quiz_attempts_created_at'), table_name='learning_quiz_attempts')
    op.drop_table('learning_quiz_attempts')
    op.drop_index(op.f('ix_learning_lesson_progress_created_at'), table_name='learning_lesson_progress')
    op.drop_table('learning_lesson_progress')
    op.drop_index(op.f('ix_learning_webhook_receipts_created_at'), table_name='learning_webhook_receipts')
    op.drop_table('learning_webhook_receipts')
    op.drop_index(op.f('ix_learning_session_registrations_created_at'), table_name='learning_session_registrations')
    op.drop_table('learning_session_registrations')
    op.drop_index(op.f('ix_learning_session_moderation_session_id'), table_name='learning_session_moderation')
    op.drop_index(op.f('ix_learning_session_moderation_created_at'), table_name='learning_session_moderation')
    op.drop_table('learning_session_moderation')
    op.drop_index(op.f('ix_learning_session_messages_session_id'), table_name='learning_session_messages')
    op.drop_index(op.f('ix_learning_session_messages_created_at'), table_name='learning_session_messages')
    op.drop_table('learning_session_messages')
    op.drop_index(op.f('ix_learning_recordings_session_id'), table_name='learning_recordings')
    op.drop_index(op.f('ix_learning_recordings_created_at'), table_name='learning_recordings')
    op.drop_table('learning_recordings')
    op.drop_index(op.f('ix_learning_lessons_module_id'), table_name='learning_lessons')
    op.drop_index(op.f('ix_learning_lessons_created_at'), table_name='learning_lessons')
    op.drop_table('learning_lessons')
    op.drop_index(op.f('ix_learning_attendance_user_id'), table_name='learning_attendance')
    op.drop_index(op.f('ix_learning_attendance_session_id'), table_name='learning_attendance')
    op.drop_index(op.f('ix_learning_attendance_created_at'), table_name='learning_attendance')
    op.drop_table('learning_attendance')
    op.drop_index(op.f('ix_learning_sessions_status'), table_name='learning_sessions')
    op.drop_index(op.f('ix_learning_sessions_starts_at'), table_name='learning_sessions')
    op.drop_index(op.f('ix_learning_sessions_educator_id'), table_name='learning_sessions')
    op.drop_index(op.f('ix_learning_sessions_created_at'), table_name='learning_sessions')
    op.drop_index(op.f('ix_learning_sessions_course_id'), table_name='learning_sessions')
    op.drop_table('learning_sessions')
    op.drop_index(op.f('ix_learning_modules_created_at'), table_name='learning_modules')
    op.drop_index(op.f('ix_learning_modules_course_id'), table_name='learning_modules')
    op.drop_table('learning_modules')
    op.drop_index(op.f('ix_learning_enrollments_created_at'), table_name='learning_enrollments')
    op.drop_table('learning_enrollments')
    op.drop_index(op.f('ix_learning_courses_status'), table_name='learning_courses')
    op.drop_index(op.f('ix_learning_courses_educator_id'), table_name='learning_courses')
    op.drop_index(op.f('ix_learning_courses_created_at'), table_name='learning_courses')
    op.drop_table('learning_courses')
    op.drop_index(op.f('ix_educator_reviews_educator_id'), table_name='educator_reviews')
    op.drop_index(op.f('ix_educator_reviews_created_at'), table_name='educator_reviews')
    op.drop_table('educator_reviews')
    op.drop_index(op.f('ix_educator_profiles_status'), table_name='educator_profiles')
    op.drop_index(op.f('ix_educator_profiles_created_at'), table_name='educator_profiles')
    op.drop_table('educator_profiles')
    # ### end Alembic commands ###
