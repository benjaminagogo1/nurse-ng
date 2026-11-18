"""Private conversation attachments and bounded upload usage.

Revision ID: e6480j0f6527
Revises: e6480i9e5416
"""

from alembic import op
import sqlalchemy as sa

revision = "e6480j0f6527"
down_revision = "e6480i9e5416"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "message_upload_usage",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="message_upload_usage_size"),
    )
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("direct_messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "sender_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "recipient_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("upload_key", sa.String(36), nullable=False),
        sa.Column("storage_name", sa.String(32), nullable=False, unique=True),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sender_id", "upload_key", name="message_attachment_upload_key"),
        sa.UniqueConstraint("message_id", "position", name="message_attachment_position"),
        sa.CheckConstraint("size_bytes > 0", name="message_attachment_size"),
        sa.CheckConstraint(
            "kind IN ('image','audio','video','document')", name="message_attachment_kind"
        ),
        sa.CheckConstraint("sender_id != recipient_id", name="message_attachment_not_self"),
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])
    op.create_index("ix_message_attachments_sender_id", "message_attachments", ["sender_id"])
    op.create_index("ix_message_attachments_created_at", "message_attachments", ["created_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM message_attachments")).scalar():
        raise RuntimeError("Remove private message attachments before downgrading their schema.")
    op.drop_table("message_attachments")
    op.drop_table("message_upload_usage")
