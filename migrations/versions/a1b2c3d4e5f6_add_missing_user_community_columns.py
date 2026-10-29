"""Add missing columns to users table via a third migration.

The original migration d7a9e3f5b1c2 added only community_name to users, but the
SQLAlchemy model also requires community_name_key and community_name_locked
columns (added later in commit e8f1a2b3c4d5). They were never reflected in any
migration, so they exist on the model but not on the live DB. This migration adds
them so authenticating a user no longer crashes with OperationalError.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "d7a9e3f5b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("community_name_key", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("community_name_locked", sa.Boolean(), nullable=False, default=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("community_name_locked")
        batch_op.drop_column("community_name_key")
