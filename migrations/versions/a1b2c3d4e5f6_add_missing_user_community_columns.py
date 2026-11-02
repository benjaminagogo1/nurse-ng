"""Compatibility marker for the former community-columns branch.

The hardening migration already owns these columns and their constraints.
Keep this revision identifier and its original branch ancestry for existing
checkouts, without adding or dropping the same columns a second time. The
branches are joined by the following merge revision.
"""

revision = "a1b2c3d4e5f6"
down_revision = "d7a9e3f5b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
