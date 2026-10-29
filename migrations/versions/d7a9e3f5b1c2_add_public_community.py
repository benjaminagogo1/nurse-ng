"""add public community

Revision ID: d7a9e3f5b1c2
Revises: c4e7a1b9d2f3
Create Date: 2026-10-28 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d7a9e3f5b1c2"
down_revision: str | None = "c4e7a1b9d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("community_name", sa.String(length=80), server_default="", nullable=False))
        batch_op.add_column(sa.Column("community_name_key", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("community_name_locked", sa.Boolean(), nullable=False, default=False, server_default="0"))

    op.create_table(
        "community_topics",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_community_topics_created_at"), "community_topics", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_topics_is_active"), "community_topics", ["is_active"], unique=False)
    op.create_index(op.f("ix_community_topics_slug"), "community_topics", ["slug"], unique=True)

    op.create_table(
        "community_posts",
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("external_video_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("removed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["removed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["topic_id"], ["community_topics.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("community_post_topic_status_idx", "community_posts", ["topic_id", "status"], unique=False)
    op.create_index(op.f("ix_community_posts_author_id"), "community_posts", ["author_id"], unique=False)
    op.create_index(op.f("ix_community_posts_created_at"), "community_posts", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_posts_published_at"), "community_posts", ["published_at"], unique=False)
    op.create_index(op.f("ix_community_posts_status"), "community_posts", ["status"], unique=False)
    op.create_index(op.f("ix_community_posts_topic_id"), "community_posts", ["topic_id"], unique=False)

    op.create_table(
        "community_media",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_name", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["post_id"], ["community_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_name"),
    )
    op.create_index(op.f("ix_community_media_created_at"), "community_media", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_media_post_id"), "community_media", ["post_id"], unique=False)

    op.create_table(
        "community_replies",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("removed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["community_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["removed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_community_replies_author_id"), "community_replies", ["author_id"], unique=False)
    op.create_index(op.f("ix_community_replies_created_at"), "community_replies", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_replies_post_id"), "community_replies", ["post_id"], unique=False)
    op.create_index(op.f("ix_community_replies_status"), "community_replies", ["status"], unique=False)

    op.create_table(
        "content_reports",
        sa.Column("reporter_id", sa.Uuid(), nullable=True),
        sa.Column("post_id", sa.Uuid(), nullable=True),
        sa.Column("reply_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("(post_id IS NOT NULL AND reply_id IS NULL) OR (post_id IS NULL AND reply_id IS NOT NULL)", name="content_report_one_target"),
        sa.ForeignKeyConstraint(["post_id"], ["community_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reply_id"], ["community_replies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("created_at", "post_id", "reply_id", "reporter_id", "status"):
        op.create_index(op.f(f"ix_content_reports_{column}"), "content_reports", [column], unique=False)

    op.create_table(
        "community_follows",
        sa.Column("follower_user_id", sa.Uuid(), nullable=False),
        sa.Column("followed_user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("follower_user_id != followed_user_id", name="community_follow_not_self"),
        sa.ForeignKeyConstraint(["followed_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["follower_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("follower_user_id", "followed_user_id", name="uniq_community_follow"),
    )
    op.create_index(op.f("ix_community_follows_created_at"), "community_follows", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_follows_followed_user_id"), "community_follows", ["followed_user_id"], unique=False)
    op.create_index(op.f("ix_community_follows_follower_user_id"), "community_follows", ["follower_user_id"], unique=False)

    op.create_table(
        "community_connections",
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("requester_user_id != recipient_user_id", name="community_connection_not_self"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requester_user_id", "recipient_user_id", name="uniq_community_connection_direction"),
    )
    op.create_index(op.f("ix_community_connections_created_at"), "community_connections", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_connections_recipient_user_id"), "community_connections", ["recipient_user_id"], unique=False)
    op.create_index(op.f("ix_community_connections_requester_user_id"), "community_connections", ["requester_user_id"], unique=False)
    op.create_index(op.f("ix_community_connections_status"), "community_connections", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("community_connections")
    op.drop_table("community_follows")
    op.drop_table("content_reports")
    op.drop_table("community_replies")
    op.drop_table("community_media")
    op.drop_table("community_posts")
    op.drop_table("community_topics")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("community_name")
