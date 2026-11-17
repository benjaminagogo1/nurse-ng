"""Profile photos, revocable sessions, email credentials and file deletion queue.

Revision ID: 7bd28ea64c10
Revises: 6a21d8e40c93
"""
from alembic import op
import sqlalchemy as sa

revision = "7bd28ea64c10"
down_revision = "6a21d8e40c93"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("account_mail_requested_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("photo_storage_name", sa.String(32), nullable=False, server_default=""))
    op.add_column("users", sa.Column("photo_public", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
    op.create_index("ix_account_tokens_expires_at", "account_tokens", ["expires_at"])
    op.create_table(
        "account_file_deletions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("storage_name", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "storage_name", name="uq_account_file_deletion"),
    )


def downgrade():
    db = op.get_bind()
    if db.execute(sa.text("SELECT count(*) FROM account_file_deletions")).scalar_one():
        raise RuntimeError("Complete queued file deletions before downgrading.")
    if db.execute(sa.text("SELECT count(*) FROM users WHERE photo_storage_name != '' OR auth_version != 0 OR email_verified_at IS NOT NULL")).scalar_one():
        raise RuntimeError("Account security or photo data exists; downgrade would discard it.")
    op.drop_table("account_file_deletions")
    op.drop_table("account_tokens")
    with op.batch_alter_table("users") as batch:
        for name in ("photo_public", "photo_storage_name", "account_mail_requested_at", "email_verified_at", "auth_version"):
            batch.drop_column(name)
