"""add login lockout columns

Revision ID: 8f2c1d4a9b6e
Revises: 253564276f57
Create Date: 2026-10-21 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '8f2c1d4a9b6e'
down_revision: str | None = '253564276f57'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode keeps the downgrade portable to SQLite, whose ALTER TABLE
    # support is narrower than PostgreSQL's (DECISIONS L42).
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column(
                'failed_login_attempts',
                sa.Integer(),
                server_default='0',
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_login_attempts')
