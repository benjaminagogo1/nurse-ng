"""Exercise migration history as well as the current model metadata."""

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, text

from app.core.config import settings


def test_fresh_and_dual_head_upgrades_preserve_accounts(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "e8f1a2b3c4d5")
    command.upgrade(config, "a1b2c3d4e5f6")
    engine = create_engine(database_url)
    account_id = uuid.uuid4().hex
    with engine.begin() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        connection.execute(users.insert().values(
            id=account_id, phone="+2348012345678", hashed_password="historical-hash",
            status="active", phone_verified=False, mfa_enabled=False,
            is_active=True, is_staff=False, community_name="Ada",
            community_name_key="ada",
        ))
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        assert set(revisions) == {
            "e8f1a2b3c4d5", "a1b2c3d4e5f6",
        }

    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        account = connection.execute(text(
            "SELECT phone, hashed_password, community_name, full_name, account_type "
            "FROM users WHERE id = :id"
        ), {"id": account_id}).one()
        assert tuple(account) == ("+2348012345678", "historical-hash", "Ada", "", "nurse")
        assert {"jobs", "job_applications", "direct_messages"} <= set(
            inspect(connection).get_table_names()
        )
    command.downgrade(config, "f9a2b3c4d5e6")
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users")).scalar_one() == account_id
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
