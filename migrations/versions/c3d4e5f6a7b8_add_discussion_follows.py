"""Add discussion follows and reply activity lookup; initialize an empty community.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discussion_follows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["community_posts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "post_id", name="uniq_discussion_follow"),
    )
    for name in ("user_id", "post_id", "created_at"):
        op.create_index(f"ix_discussion_follows_{name}", "discussion_follows", [name])
    op.create_index("community_reply_activity_idx", "community_replies", ["post_id", "status", "created_at"])

    topics = sa.table(
        "community_topics", sa.column("id", sa.Uuid()), sa.column("name"),
        sa.column("slug"), sa.column("description"), sa.column("is_active", sa.Boolean()),
    )
    connection = op.get_bind()
    if connection.scalar(sa.select(sa.func.count()).select_from(topics)) == 0:
        # A category only; never seed posts, replies, people, or engagement.
        connection.execute(topics.insert().values(
            id=uuid.UUID("019a58a0-0000-7000-8000-000000000001"),
            name="General nursing", slug="general-nursing",
            description="Questions, useful information, and everyday life as a nurse.",
            is_active=True,
        ))


def downgrade() -> None:
    op.drop_index("community_reply_activity_idx", table_name="community_replies")
    op.drop_table("discussion_follows")
    # Keep the category: real conversations may now refer to it.
