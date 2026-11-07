"""add approved source vacancy ingestion

Revision ID: 3838cd201521
Revises: a3310f4d2d7b
Create Date: 2026-11-07 20:57:27.033656

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "3838cd201521"
down_revision: str | None = "a3310f4d2d7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recruitment_sources") as batch:
        batch.add_column(
            sa.Column("collection_adapter", sa.String(20), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column("vacancy_url_prefix", sa.String(2048), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column("deadline_timezone", sa.String(80), server_default="", nullable=False)
        )
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("source_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("external_key", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("country_code", sa.String(length=2), server_default="", nullable=False)
        )
        batch.add_column(
            sa.Column("normalized_data", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.add_column(sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
        batch.alter_column("employer_user_id", existing_type=sa.CHAR(length=32), nullable=True)
        batch.alter_column(
            "title",
            existing_type=sa.VARCHAR(length=120),
            type_=sa.String(length=250),
            existing_nullable=False,
        )
        batch.alter_column(
            "organization",
            existing_type=sa.VARCHAR(length=160),
            type_=sa.String(length=250),
            existing_nullable=False,
        )
        batch.alter_column(
            "location",
            existing_type=sa.VARCHAR(length=120),
            type_=sa.String(length=250),
            existing_nullable=False,
        )
        batch.create_index(op.f("ix_jobs_closes_at"), ["closes_at"], unique=False)
        batch.create_index(op.f("ix_jobs_country_code"), ["country_code"], unique=False)
        batch.create_index(op.f("ix_jobs_source_id"), ["source_id"], unique=False)
        batch.create_unique_constraint("uq_jobs_external_key", ["external_key"])
        batch.create_check_constraint(
            "ck_job_channel",
            "(source_id IS NULL AND employer_user_id IS NOT NULL AND external_key IS NULL) OR "
            "(source_id IS NOT NULL AND employer_user_id IS NULL AND external_key IS NOT NULL)",
        )
        batch.create_foreign_key(
            "fk_job_recruitment_source",
            "recruitment_sources",
            ["source_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_table(
        "vacancy_snapshots",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("original_url", sa.String(length=2048), nullable=False),
        sa.Column("observed_url", sa.String(length=2048), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adapter", sa.String(length=40), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["recruitment_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_vacancy_snapshot"),
    )
    op.create_index(
        op.f("ix_vacancy_snapshots_source_id"), "vacancy_snapshots", ["source_id"], unique=False
    )
    op.create_table(
        "vacancy_records",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("record_key", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("raw_record", sa.JSON(), nullable=False),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["vacancy_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["recruitment_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "record_key", name="uq_vacancy_source_record"),
    )
    op.create_index(op.f("ix_vacancy_records_job_id"), "vacancy_records", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_vacancy_records_source_id"), "vacancy_records", ["source_id"], unique=False
    )
    op.create_index(op.f("ix_vacancy_records_state"), "vacancy_records", ["state"], unique=False)
    op.create_table(
        "vacancy_events",
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["record_id"], ["vacancy_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["vacancy_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vacancy_events_created_at"), "vacancy_events", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_vacancy_events_record_id"), "vacancy_events", ["record_id"], unique=False
    )


def downgrade() -> None:
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text("SELECT count(*) FROM jobs WHERE source_id IS NOT NULL")
        ).scalar()
        or connection.execute(sa.text("SELECT count(*) FROM vacancy_snapshots")).scalar()
    ):
        raise RuntimeError(
            "Downgrade refused: archive vacancy jobs and original records before reverting this schema."
        )
    op.drop_table("vacancy_events")
    op.drop_table("vacancy_records")
    op.drop_table("vacancy_snapshots")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("fk_job_recruitment_source", type_="foreignkey")
        batch.drop_constraint("uq_jobs_external_key", type_="unique")
        batch.drop_constraint("ck_job_channel", type_="check")
        batch.drop_index("ix_jobs_source_id")
        batch.drop_index("ix_jobs_country_code")
        batch.drop_index("ix_jobs_closes_at")
        batch.alter_column(
            "location", existing_type=sa.String(250), type_=sa.String(120), existing_nullable=False
        )
        batch.alter_column(
            "organization",
            existing_type=sa.String(250),
            type_=sa.String(160),
            existing_nullable=False,
        )
        batch.alter_column(
            "title", existing_type=sa.String(250), type_=sa.String(120), existing_nullable=False
        )
        batch.alter_column("employer_user_id", existing_type=sa.Uuid(), nullable=False)
        for column in (
            "confirmed_at",
            "opens_at",
            "closes_at",
            "normalized_data",
            "country_code",
            "external_key",
            "source_id",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("recruitment_sources") as batch:
        batch.drop_column("deadline_timezone")
        batch.drop_column("vacancy_url_prefix")
        batch.drop_column("collection_adapter")
