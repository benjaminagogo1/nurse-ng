"""Private session-bound resumable Reel upload metadata."""

from alembic import op
import sqlalchemy as sa

revision = "e6480c2ea831"
down_revision = "e6480b1d9a72"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "offline_uploads",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("upload_id", sa.Uuid(), primary_key=True),
        sa.Column("session_scope", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("received", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publication_hash", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_offline_uploads_created_at", "offline_uploads", ["created_at"])
    op.create_index("ix_offline_uploads_expires_at", "offline_uploads", ["expires_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM offline_uploads")).scalar_one():
        raise RuntimeError("Retire resumable upload clients before removing staging metadata.")
    op.drop_table("offline_uploads")
