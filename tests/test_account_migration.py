"""Preserve existing identities while adding account-security and photo state."""

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text

from app.core.config import settings


def test_account_upgrade_preserves_user_and_revocable_session_defaults(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'account-migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "6a21d8e40c93")
    engine = create_engine(url)
    identifier = uuid.uuid4()
    with engine.begin() as conn:
        users = Table("users", MetaData(), autoload_with=conn)
        conn.execute(
            users.insert().values(
                id=identifier.hex,
                phone="+2348011111122",
                email="old@example.org",
                hashed_password="preserved-password-hash",
                full_name="Existing member",
                status="active",
                phone_verified=False,
                mfa_enabled=False,
                is_active=True,
                is_staff=True,
            )
        )
        before = dict(conn.execute(users.select()).mappings().one())
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as conn:
        users = Table("users", MetaData(), autoload_with=conn)
        after = dict(conn.execute(users.select()).mappings().one())
        assert {key: after[key] for key in before} == before
        assert after["auth_version"] == 0 and not after["photo_public"]
        assert after["photo_storage_name"] == "" and after["email_verified_at"] is None
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        conn.execute(users.update().values(auth_version=1))
    with pytest.raises(RuntimeError, match="security or photo data"):
        command.downgrade(config, "6a21d8e40c93")
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET auth_version=0"))
    command.downgrade(config, "6a21d8e40c93")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
