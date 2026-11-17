"""harden community trust and abuse controls

Revision ID: e8f1a2b3c4d5
Revises: d7a9e3f5b1c2
Create Date: 2026-10-28 00:00:00.000000

"""
import unicodedata
import uuid
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e8f1a2b3c4d5"
down_revision: str | None = "d7a9e3f5b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_hex(value: object) -> str:
    return uuid.UUID(str(value)).hex


def _community_name_key(value: str) -> str:
    normalised = unicodedata.normalize("NFKC", value)
    return " ".join(normalised.split()).casefold()


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("community_name_key", sa.String(160), nullable=True))
        batch_op.add_column(
            sa.Column(
                "community_name_locked",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "community_storage_bytes",
                sa.BigInteger(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "community_upload_window_started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "community_upload_window_bytes",
                sa.BigInteger(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )

    with op.batch_alter_table("nurse_profiles") as batch_op:
        batch_op.add_column(
            sa.Column("document_reviewed_name", sa.String(120), nullable=True)
        )

    with op.batch_alter_table("verification_cases") as batch_op:
        batch_op.add_column(
            sa.Column("reviewed_display_name", sa.String(120), nullable=True)
        )

    with op.batch_alter_table("content_reports") as batch_op:
        batch_op.add_column(sa.Column("open_key", sa.String(80), nullable=True))

    with op.batch_alter_table("community_connections") as batch_op:
        batch_op.add_column(sa.Column("pair_key", sa.String(65), nullable=True))

    bind = op.get_bind()
    seen_names: set[str] = set()
    users = bind.execute(
        sa.text("SELECT id, community_name FROM users WHERE community_name != ''")
    ).mappings()
    for row in users:
        key = _community_name_key(row["community_name"])
        if key in seen_names:
            raise RuntimeError("Duplicate community names must be resolved before migration.")
        seen_names.add(key)
        bind.execute(
            sa.text("UPDATE users SET community_name_key = :key WHERE id = :id"),
            {"key": key, "id": row["id"]},
        )

    bind.execute(
        sa.text(
            "UPDATE nurse_profiles "
            "SET document_reviewed_name = display_name "
            "WHERE document_reviewed_at IS NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE verification_cases "
            "SET reviewed_display_name = ("
            "SELECT nurse_profiles.display_name FROM nurse_profiles "
            "WHERE nurse_profiles.id = verification_cases.profile_id"
            ") WHERE status = 'approved'"
        )
    )

    seen_pairs: set[str] = set()
    connections = bind.execute(
        sa.text(
            "SELECT id, requester_user_id, recipient_user_id "
            "FROM community_connections"
        )
    ).mappings()
    for row in connections:
        first, second = sorted(
            (_uuid_hex(row["requester_user_id"]), _uuid_hex(row["recipient_user_id"]))
        )
        pair_key = f"{first}:{second}"
        if pair_key in seen_pairs:
            raise RuntimeError(
                "Reciprocal connection rows must be resolved before migration."
            )
        seen_pairs.add(pair_key)
        bind.execute(
            sa.text(
                "UPDATE community_connections SET pair_key = :pair_key WHERE id = :id"
            ),
            {"pair_key": pair_key, "id": row["id"]},
        )

    seen_reports: set[str] = set()
    reports = bind.execute(
        sa.text(
            "SELECT id, reporter_id, post_id, reply_id FROM content_reports "
            "WHERE status = 'open' AND reporter_id IS NOT NULL"
        )
    ).mappings()
    for row in reports:
        reporter = _uuid_hex(row["reporter_id"])
        if row["post_id"] is not None:
            open_key = f"post:{reporter}:{_uuid_hex(row['post_id'])}"
        else:
            open_key = f"reply:{reporter}:{_uuid_hex(row['reply_id'])}"
        if open_key in seen_reports:
            raise RuntimeError("Duplicate open reports must be resolved before migration.")
        seen_reports.add(open_key)
        bind.execute(
            sa.text("UPDATE content_reports SET open_key = :open_key WHERE id = :id"),
            {"open_key": open_key, "id": row["id"]},
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.create_unique_constraint(
            "uniq_users_community_name_key", ["community_name_key"]
        )
        batch_op.create_check_constraint(
            "community_byte_counters_nonnegative",
            "community_storage_bytes >= 0 AND community_upload_window_bytes >= 0",
        )

    with op.batch_alter_table("content_reports") as batch_op:
        batch_op.create_unique_constraint(
            "uniq_content_report_open_key", ["open_key"]
        )

    with op.batch_alter_table("community_connections") as batch_op:
        batch_op.alter_column("pair_key", existing_type=sa.String(65), nullable=False)
        batch_op.create_unique_constraint(
            "uniq_community_connection_pair", ["pair_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("community_connections") as batch_op:
        batch_op.drop_constraint("uniq_community_connection_pair", type_="unique")
        batch_op.drop_column("pair_key")

    with op.batch_alter_table("content_reports") as batch_op:
        batch_op.drop_constraint("uniq_content_report_open_key", type_="unique")
        batch_op.drop_column("open_key")

    with op.batch_alter_table("verification_cases") as batch_op:
        batch_op.drop_column("reviewed_display_name")

    with op.batch_alter_table("nurse_profiles") as batch_op:
        batch_op.drop_column("document_reviewed_name")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("community_byte_counters_nonnegative", type_="check")
        batch_op.drop_constraint("uniq_users_community_name_key", type_="unique")
        batch_op.drop_column("community_upload_window_bytes")
        batch_op.drop_column("community_upload_window_started_at")
        batch_op.drop_column("community_storage_bytes")
        batch_op.drop_column("community_name_locked")
        batch_op.drop_column("community_name_key")
