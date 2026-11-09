"""Notification inbox, preferences, durable email and idempotent message sending.

Revision ID: 9de420c3b287
Revises: 8cf309b2a176
"""

from alembic import op
import sqlalchemy as sa

revision = "9de420c3b287"
down_revision = "8cf309b2a176"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("direct_messages") as batch:
        batch.add_column(sa.Column("client_key", sa.String(36)))
        batch.create_unique_constraint("uq_message_sender_client_key", ["sender_id", "client_key"])
        batch.create_index("message_thread_idx", ["sender_id", "recipient_id", "created_at", "id"])
    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("category", sa.String(24), primary_key=True),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_notification_preferences_created_at", "notification_preferences", ["created_at"]
    )
    columns = [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "recipient_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("application_status", sa.String(24), nullable=False),
        sa.Column("email_to", sa.String(254), nullable=False),
        sa.Column("email_state", sa.String(16), nullable=False),
        sa.Column("email_attempts", sa.Integer(), nullable=False),
        sa.Column("email_next_attempt", sa.DateTime(timezone=True)),
        sa.Column("email_lease_until", sa.DateTime(timezone=True)),
        sa.Column("email_lease_token", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]
    for name, table in [
        ("post_id", "community_posts"),
        ("reply_id", "community_replies"),
        ("connection_id", "community_connections"),
        ("message_id", "direct_messages"),
        ("application_id", "job_applications"),
    ]:
        columns.append(sa.Column(name, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete="CASCADE")))
    op.create_table(
        "notifications",
        *columns,
        sa.UniqueConstraint("recipient_id", "event_key", name="uq_notification_event_recipient"),
    )
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index(
        "notification_inbox_idx", "notifications", ["recipient_id", "in_app", "created_at", "id"]
    )
    op.create_index("notification_unread_idx", "notifications", ["recipient_id", "read_at"])
    op.create_index(
        "notification_delivery_idx", "notifications", ["email_state", "email_next_attempt"]
    )


def downgrade():
    db = op.get_bind()
    for table in ("notifications", "notification_preferences"):
        if db.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("Notification data exists; export it before downgrading.")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    with op.batch_alter_table("direct_messages") as batch:
        batch.drop_index("message_thread_idx")
        batch.drop_constraint("uq_message_sender_client_key", type_="unique")
        batch.drop_column("client_key")
