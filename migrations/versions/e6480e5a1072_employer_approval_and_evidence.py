"""Require reviewed employer membership and scanned evidence, without trusting legacy rows."""

from alembic import op
import sqlalchemy as sa

revision = "e6480e5a1072"
down_revision = "e6480d3fb942"
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.create_table("employer_organizations", *common(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("name_key", sa.String(320), nullable=False, unique=True),
        sa.Column("website", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.create_table("employer_memberships", *common(),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("employer_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("authority_details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_employer_member"),
    )
    op.create_table("employer_review_events", *common(),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("employer_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("membership_id", sa.Uuid(), sa.ForeignKey("employer_memberships.id", ondelete="SET NULL")),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
    )
    for table, columns in {
        "employer_organizations": ["created_at"],
        "employer_memberships": ["created_at", "organization_id", "user_id"],
        "employer_review_events": ["created_at", "organization_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("employer_organization_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_jobs_employer_organization_id", "employer_organizations",
                                 ["employer_organization_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_jobs_employer_organization_id", ["employer_organization_id"])
    with op.batch_alter_table("evidence_documents") as batch:
        batch.add_column(sa.Column("scan_status", sa.String(20), server_default="pending", nullable=False))
        batch.add_column(sa.Column("scanned_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("purged_at", sa.DateTime(timezone=True)))


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM employer_memberships")) or connection.scalar(
        sa.text("SELECT COUNT(*) FROM evidence_documents WHERE scan_status <> 'pending' OR purged_at IS NOT NULL")
    ):
        raise RuntimeError("Cannot discard employer approval or evidence safety records.")
    with op.batch_alter_table("evidence_documents") as batch:
        for column in ["purged_at", "scanned_at", "scan_status"]:
            batch.drop_column(column)
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_employer_organization_id")
        batch.drop_constraint("fk_jobs_employer_organization_id", type_="foreignkey")
        batch.drop_column("employer_organization_id")
    for table in ["employer_review_events", "employer_memberships", "employer_organizations"]:
        op.drop_table(table)
