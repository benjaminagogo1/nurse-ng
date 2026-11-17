"""Bind source activation to explicitly recorded reuse scope.

Revision ID: 49b37f820e16
Revises: 3838cd201521
"""

from alembic import op
import sqlalchemy as sa

revision = "49b37f820e16"
down_revision = "3838cd201521"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing decisions remain in the audit history. Do not infer rights from them.
    op.add_column(
        "recruitment_sources",
        sa.Column("reuse_basis", sa.String(30), nullable=False, server_default=""),
    )
    op.add_column(
        "recruitment_sources",
        sa.Column("reuse_url_prefix", sa.String(2048), nullable=False, server_default=""),
    )
    for name in ("allow_collection", "allow_snapshot_retention", "allow_republication"):
        op.add_column(
            "recruitment_sources", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM recruitment_sources WHERE reuse_basis != ''")
    ).scalar_one():
        raise RuntimeError("Explicitly archive recorded reuse decisions before downgrading.")
    with op.batch_alter_table("recruitment_sources") as batch:
        for name in (
            "allow_republication",
            "allow_snapshot_retention",
            "allow_collection",
            "reuse_url_prefix",
            "reuse_basis",
        ):
            batch.drop_column(name)
