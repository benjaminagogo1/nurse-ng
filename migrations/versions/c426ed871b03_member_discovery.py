"""Private-by-default professional interests and optional onboarding progress."""

from alembic import op
import sqlalchemy as sa

revision = "c426ed871b03"
down_revision = "b715a203ce46"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("nurse_profiles", sa.Column("interests", sa.String(600), nullable=False, server_default=""))
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True)))


def downgrade():
    db = op.get_bind()
    if db.execute(sa.text("SELECT count(*) FROM nurse_profiles WHERE interests <> ''")).scalar_one():
        raise RuntimeError("Member interests exist; export them before downgrading.")
    if db.execute(sa.text("SELECT count(*) FROM users WHERE onboarding_completed_at IS NOT NULL")).scalar_one():
        raise RuntimeError("Onboarding progress exists; export it before downgrading.")
    op.drop_column("users", "onboarding_completed_at")
    op.drop_column("nurse_profiles", "interests")
