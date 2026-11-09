"""Private daily activity, without inferring visits from historical account changes."""

from alembic import op
import sqlalchemy as sa

revision = "d537f982ac14"
down_revision = "c426ed871b03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_daily_activity",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("first_seen_at <= last_seen_at", name="activity_time_order"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "activity_date"),
    )
    op.create_index("ix_user_daily_activity_activity_date", "user_daily_activity", ["activity_date"])
    op.create_index("ix_user_daily_activity_last_seen_at", "user_daily_activity", ["last_seen_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM user_daily_activity")).scalar_one():
        raise RuntimeError("Activity history exists; export it before downgrading.")
    op.drop_table("user_daily_activity")
