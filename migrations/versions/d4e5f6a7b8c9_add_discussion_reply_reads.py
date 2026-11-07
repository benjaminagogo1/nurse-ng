"""Track opened replies without clearing skipped pages.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discussion_reply_reads",
        sa.Column("follow_id", sa.Uuid(), nullable=False),
        sa.Column("reply_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("follow_id", "reply_id"),
        sa.ForeignKeyConstraint(["follow_id"], ["discussion_follows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reply_id"], ["community_replies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_discussion_reply_reads_reply_id", "discussion_reply_reads", ["reply_id"])


def downgrade() -> None:
    op.drop_table("discussion_reply_reads")
