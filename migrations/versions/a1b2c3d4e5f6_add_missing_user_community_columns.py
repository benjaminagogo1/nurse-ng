"""Add missing columns to users table defensively.

The original migration d7a9e3f5b1c2 added only `community_name` to users, but the
SQLAlchemy model also requires `community_name_key` and
`community_name_locked`. Migration e8f1a2b3c4d5 adds those columns later, after the
public-community work landed. Nothing in the earlier chain reflected that the model
needs two extra columns now, so this migration is safe to skip if those
columns already exist on an upgraded database. Downgrade is symmetric.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "d7a9e3f5b1c2"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    try:
        return {row[0] for row in bind.exec_driver_sql(
            "SELECT name FROM information_schema.columns WHERE table_name=%s" % table_name
        ).fetchall()}
    except Exception:  # non-SQLite backend falls back to PRAGMA
        return {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(%s)" % table_name).fetchall()}


def upgrade() -> None:
    existing = _existing_columns("users")
    if "community_name_key" not in existing:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("community_name_key", sa.String(length=160), nullable=True))
    if "community_name_locked" not in existing:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("community_name_locked", sa.Boolean(), nullable=False, default=False, server_default="0"))


def downgrade() -> None:
    existing = _existing_columns("users")
    for column in ("community_name_locked", "community_name_key"):
        if column in existing:
            with op.batch_alter_table("users") as batch_op:
                batch_op.drop_column(column)
