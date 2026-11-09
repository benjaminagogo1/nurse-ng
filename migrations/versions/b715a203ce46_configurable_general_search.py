"""Configurable general web search alongside existing directory and Brave schedules.

Revision ID: b715a203ce46
Revises: ae5314d8c902
"""
from alembic import op
import sqlalchemy as sa

revision = 'b715a203ce46'
down_revision = 'ae5314d8c902'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('recruitment_discovery_schedules') as batch:
        batch.drop_constraint('ck_discovery_provider', type_='check')
        batch.create_check_constraint('ck_discovery_provider', "provider IN ('ror', 'brave', 'search')")
    with op.batch_alter_table('recruitment_discovery_tasks') as batch:
        batch.drop_constraint('ck_discovery_task_kind', type_='check')
        batch.create_check_constraint('ck_discovery_task_kind', "kind IN ('ror', 'brave', 'search', 'inspect')")


def downgrade():
    db = op.get_bind()
    if db.execute(sa.text("SELECT count(*) FROM recruitment_discovery_schedules WHERE provider = 'search'")).scalar_one() or db.execute(sa.text("SELECT count(*) FROM recruitment_discovery_tasks WHERE kind = 'search'")).scalar_one():
        raise RuntimeError('General search history exists; export it before downgrading.')
    with op.batch_alter_table('recruitment_discovery_tasks') as batch:
        batch.drop_constraint('ck_discovery_task_kind', type_='check')
        batch.create_check_constraint('ck_discovery_task_kind', "kind IN ('ror', 'brave', 'inspect')")
    with op.batch_alter_table('recruitment_discovery_schedules') as batch:
        batch.drop_constraint('ck_discovery_provider', type_='check')
        batch.create_check_constraint('ck_discovery_provider', "provider IN ('ror', 'brave')")
