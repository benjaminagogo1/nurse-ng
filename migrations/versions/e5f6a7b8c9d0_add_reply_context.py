"""Link responses to the reply they answer.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("community_replies") as batch:
        batch.add_column(sa.Column("in_reply_to_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_community_reply_parent", "community_replies", ["in_reply_to_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "community_reply_not_self", "in_reply_to_id IS NULL OR in_reply_to_id != id",
        )
        batch.create_index("ix_community_replies_in_reply_to_id", ["in_reply_to_id"])


def downgrade() -> None:
    with op.batch_alter_table("community_replies") as batch:
        batch.drop_index("ix_community_replies_in_reply_to_id")
        batch.drop_constraint("community_reply_not_self", type_="check")
        batch.drop_constraint("fk_community_reply_parent", type_="foreignkey")
        batch.drop_column("in_reply_to_id")
