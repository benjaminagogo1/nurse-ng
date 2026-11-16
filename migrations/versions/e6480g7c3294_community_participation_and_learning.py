"""Joinable communities, helpful answers, learning activities and sign-in continuity.

Revision ID: e6480g7c3294
Revises: e6480f6b2183
"""

from alembic import op
import sqlalchemy as sa

revision = "e6480g7c3294"
down_revision = "e6480f6b2183"
branch_labels = None
depends_on = None


def upgrade():
    for name, length in [("welcome_text", 1000), ("rules", 2000), ("interest", 80)]:
        op.add_column(
            "community_topics",
            sa.Column(name, sa.String(length), nullable=False, server_default=""),
        )
    with op.batch_alter_table("community_posts") as batch:
        batch.add_column(
            sa.Column("post_kind", sa.String(20), nullable=False, server_default="discussion")
        )
        batch.add_column(sa.Column("title", sa.String(160), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("activity_format", sa.String(20), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("activity_starts_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_community_posts_post_kind", ["post_kind"])
        batch.create_check_constraint(
            "community_post_kind", "post_kind IN ('discussion','question','experience','activity')"
        )
        batch.create_check_constraint(
            "community_activity_details",
            "post_kind != 'activity' OR "
            "(title != '' AND activity_format IN ('discussion','practice','q-and-a'))",
        )
    op.create_table(
        "community_memberships",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "topic_id",
            sa.Uuid(),
            sa.ForeignKey("community_topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_community_memberships_topic_id", "community_memberships", ["topic_id"])
    op.create_table(
        "community_helpful_replies",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "reply_id",
            sa.Uuid(),
            sa.ForeignKey("community_replies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_community_helpful_replies_reply_id", "community_helpful_replies", ["reply_id"]
    )
    op.create_table(
        "community_answers",
        sa.Column(
            "post_id",
            sa.Uuid(),
            sa.ForeignKey("community_posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "reply_id",
            sa.Uuid(),
            sa.ForeignKey("community_replies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "selected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for table in ("social_auth_attempts", "social_enrollments"):
        op.add_column(
            table, sa.Column("return_to", sa.String(240), nullable=False, server_default="")
        )


def downgrade():
    for table in ("social_enrollments", "social_auth_attempts"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("return_to")
    op.drop_table("community_answers")
    op.drop_table("community_helpful_replies")
    op.drop_table("community_memberships")
    with op.batch_alter_table("community_posts") as batch:
        batch.drop_constraint("community_activity_details", type_="check")
        batch.drop_constraint("community_post_kind", type_="check")
        batch.drop_index("ix_community_posts_post_kind")
        for column in ("activity_starts_at", "activity_format", "title", "post_kind"):
            batch.drop_column(column)
    with op.batch_alter_table("community_topics") as batch:
        for column in ("interest", "rules", "welcome_text"):
            batch.drop_column(column)
