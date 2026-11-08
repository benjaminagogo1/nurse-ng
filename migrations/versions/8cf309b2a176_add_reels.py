"""Reels processing queue and private saves, reusing community posts and media.

Revision ID: 8cf309b2a176
Revises: 7bd28ea64c10
"""
from alembic import op
import sqlalchemy as sa

revision = "8cf309b2a176"
down_revision = "7bd28ea64c10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reels",
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("community_posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("upload_key", sa.String(36), nullable=False, unique=True),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("captions", sa.Text(), nullable=False),
        sa.Column("cover_seconds", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('queued','processing','ready','failed')", name="reel_state"),
        sa.CheckConstraint("audience IN ('nigeria','global')", name="reel_audience"),
        sa.CheckConstraint("category IN ('opportunities','career','learning','stories')", name="reel_category"),
    )
    for column in ("category", "audience", "state", "created_at"):
        op.create_index(f"ix_reels_{column}", "reels", [column])
    op.create_table(
        "reel_saves",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("reels.post_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reel_saves_post_id", "reel_saves", ["post_id"])
    op.create_index("ix_reel_saves_created_at", "reel_saves", ["created_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM reels")).scalar_one():
        raise RuntimeError("Reels exist; export or remove them before downgrading.")
    op.drop_table("reel_saves")
    op.drop_table("reels")
