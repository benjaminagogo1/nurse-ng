"""Durable worker progress and readiness without altering accounts or task leases."""

from alembic import op
import sqlalchemy as sa

revision = "e6480d3fb942"
down_revision = "e6480c2ea831"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_heartbeats",
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("instance_id", sa.String(32), primary_key=True),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=False),
    )
    op.create_index("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])


def downgrade():
    op.drop_table("worker_heartbeats")
