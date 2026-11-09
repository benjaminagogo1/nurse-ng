"""Account-scoped interactive tour, separate from interest onboarding."""

from alembic import op
import sqlalchemy as sa

revision = "e6480ab31c95"
down_revision = "d537f982ac14"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_tours",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("step_key", sa.String(48), nullable=True),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('offered', 'active', 'completed', 'skipped')", name="tour_status"),
        sa.CheckConstraint("version > 0 AND revision >= 0", name="tour_versions"),
        sa.CheckConstraint(
            "status != 'active' OR (run_id IS NOT NULL AND step_key IS NOT NULL "
            "AND started_at IS NOT NULL AND finished_at IS NULL)", name="tour_active_progress",
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'skipped') OR finished_at IS NOT NULL", name="tour_finished_time",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM user_tours")).scalar_one():
        raise RuntimeError("Tour preferences exist; export them before downgrading.")
    op.drop_table("user_tours")
