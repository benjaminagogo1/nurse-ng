"""Add shared video likes and an administrative role audit without changing accounts."""

from alembic import op
import sqlalchemy as sa

revision = "e6480f6b2183"
down_revision = "e6480e5a1072"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "community_post_likes",
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("community_posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_community_post_likes_user_id", "community_post_likes", ["user_id"])
    op.create_table(
        "staff_role_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_staff_role_events_created_at", "staff_role_events", ["created_at"])


def downgrade():
    connection = op.get_bind()
    for table in ("community_post_likes", "staff_role_events"):
        if connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Cannot discard recorded likes or administrative decisions.")
    op.drop_table("staff_role_events")
    op.drop_table("community_post_likes")
