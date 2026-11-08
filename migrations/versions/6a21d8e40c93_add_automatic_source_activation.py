"""Track automatic source activation without replacing staff decisions.

Revision ID: 6a21d8e40c93
Revises: 49b37f820e16
"""

from alembic import op
import sqlalchemy as sa

revision = "6a21d8e40c93"
down_revision = "49b37f820e16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recruitment_sources", sa.Column(
        "approval_mode", sa.String(20), nullable=False, server_default="",
    ))
    op.add_column("recruitment_sources", sa.Column(
        "activation_review", sa.JSON(), nullable=False, server_default="{}",
    ))
    op.execute(sa.text("""
        UPDATE recruitment_sources SET approval_mode = 'staff'
        WHERE verification_status != 'pending' OR collection_adapter != ''
        OR EXISTS (
            SELECT 1 FROM recruitment_source_events e
            WHERE e.source_id = recruitment_sources.id
            AND e.kind IN ('approve', 'reject', 'revoke', 'reopen',
                           'organisation_updated', 'collector_configured')
        )
    """))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT count(*) FROM recruitment_sources WHERE approval_mode = 'automatic'"
    )).scalar_one():
        raise RuntimeError("Review or revoke automatically activated sources before downgrading.")
    with op.batch_alter_table("recruitment_sources") as batch:
        batch.drop_column("activation_review")
        batch.drop_column("approval_mode")
