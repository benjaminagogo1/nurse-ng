"""Atomic offline operation receipts without retaining request bodies."""

from alembic import op
import sqlalchemy as sa

revision = "e6480b1d9a72"
down_revision = "e6480ac93d25"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "offline_operations",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_offline_operations_created_at", "offline_operations", ["created_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM offline_operations")).scalar_one():
        raise RuntimeError("Retain operation receipts until all offline clients are retired.")
    op.drop_table("offline_operations")
