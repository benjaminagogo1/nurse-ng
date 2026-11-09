"""Private opportunity saves, matching criteria and system notification targets.

Revision ID: ae5314d8c902
Revises: 9de420c3b287
"""
from alembic import op
import sqlalchemy as sa

revision = "ae5314d8c902"
down_revision = "9de420c3b287"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
            for name in ("created_at", "updated_at")]


def upgrade():
    op.create_table("saved_opportunities",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("remind", sa.Boolean(), nullable=False),
        sa.Column("reminded_deadline", sa.DateTime(timezone=True)), *timestamps())
    op.create_index("ix_saved_opportunities_created_at", "saved_opportunities", ["created_at"])
    op.create_table("opportunity_preferences",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("keyword", sa.String(120), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("job_type", sa.String(20), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("active_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False), *timestamps())
    op.create_index("ix_opportunity_preferences_created_at", "opportunity_preferences", ["created_at"])
    op.create_index("ix_opportunity_preferences_next_check_at", "opportunity_preferences", ["next_check_at"])
    with op.batch_alter_table("notifications") as batch:
        batch.alter_column("actor_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("job_id", sa.Uuid()))
        batch.add_column(sa.Column("deadline_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key("fk_notification_job", "jobs", ["job_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_notifications_job_id", ["job_id"])


def downgrade():
    db = op.get_bind()
    for table in ("saved_opportunities", "opportunity_preferences"):
        if db.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("Opportunity data exists; export it before downgrading.")
    if db.execute(sa.text("SELECT count(*) FROM notifications WHERE actor_id IS NULL OR job_id IS NOT NULL")).scalar_one():
        raise RuntimeError("Opportunity notifications exist; export them before downgrading.")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_index("ix_notifications_job_id")
        batch.drop_constraint("fk_notification_job", type_="foreignkey")
        batch.drop_column("job_id")
        batch.drop_column("deadline_at")
        batch.alter_column("actor_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("saved_opportunities")
    op.drop_table("opportunity_preferences")
