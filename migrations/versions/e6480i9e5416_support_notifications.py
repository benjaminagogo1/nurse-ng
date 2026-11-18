"""Connect private peer support to the existing notification inbox.

Revision ID: e6480i9e5416
Revises: e6480h8d4305
"""

from alembic import op
import sqlalchemy as sa

revision = "e6480i9e5416"
down_revision = "e6480h8d4305"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(sa.Column("mentorship_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("notification_mentorship_fk", "mentorship_requests",
                                 ["mentorship_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_notifications_mentorship_id", ["mentorship_id"])


def downgrade():
    with op.batch_alter_table("notifications") as batch:
        batch.drop_index("ix_notifications_mentorship_id")
        batch.drop_constraint("notification_mentorship_fk", type_="foreignkey")
        batch.drop_column("mentorship_id")
