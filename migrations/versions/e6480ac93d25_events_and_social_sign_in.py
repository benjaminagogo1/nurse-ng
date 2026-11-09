"""Community events and browser-bound provider sign-in, preserving existing accounts."""

from alembic import op
import sqlalchemy as sa

revision = "e6480ac93d25"
down_revision = "e6480ab31c95"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "community_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(240), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registration_url", sa.String(2048), server_default="", nullable=False),
        sa.Column("status", sa.String(20), server_default="scheduled", nullable=False),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint("ends_at > starts_at", name="event_time_order"),
        sa.CheckConstraint("status IN ('scheduled', 'cancelled')", name="event_status_valid"),
    )
    for column in ("created_at", "starts_at"):
        op.create_index(f"ix_community_events_{column}", "community_events", [column])
    op.create_table(
        "event_attendance",
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("community_events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "social_identities",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("subject", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="social_user_provider"),
    )
    op.create_index("ix_social_identities_user_id", "social_identities", ["user_id"])
    for table, columns in (
        ("social_auth_attempts", [
            sa.Column("nonce", sa.String(64), nullable=False),
            sa.Column("verifier", sa.String(128), nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
            sa.Column("auth_version", sa.Integer()),
        ]),
        ("social_enrollments", [
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("full_name", sa.String(120), nullable=False),
        ]),
    ):
        op.create_table(
            table,
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column("browser_hash", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            *columns,
        )
        op.create_index(f"ix_{table}_expires_at", table, ["expires_at"])


def downgrade():
    for table in ("community_events", "social_identities"):
        if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("Export events and disconnect provider identities before downgrading.")
    for table in ("social_enrollments", "social_auth_attempts", "social_identities",
                  "event_attendance", "community_events"):
        op.drop_table(table)
