"""Offline metadata upgrades preserve accounts and protect outstanding receipts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import enable_sqlite_foreign_keys
from app.models.offline import OfflineOperation
from app.models.offline_upload import OfflineUpload
from tests.test_migrations import historical_user


def test_offline_upgrade_preserves_accounts_receipts_and_uploads(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'offline-migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "e6480ac93d25")
    engine = create_engine(url)
    enable_sqlite_foreign_keys(engine)
    with Session(engine) as db:
        user_id = historical_user(
            db, phone="+2348012345678", hashed_password="historical-hash"
        ).id
        db.commit()
        before = list(db.execute(text("SELECT * FROM users")))
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        assert list(db.execute(text("SELECT * FROM users"))) == before
        assert db.scalar(text("SELECT count(*) FROM offline_operations")) == 0
        assert db.scalar(text("SELECT count(*) FROM offline_uploads")) == 0
        db.add(OfflineOperation(
            user_id=user_id, operation_id=uuid4(), kind="profile", payload_hash="a" * 64,
            result={"path": "/profile", "message": "Synchronized"},
        ))
        db.add(OfflineUpload(
            user_id=user_id, upload_id=uuid4(), session_scope="b" * 64, size=100, received=0,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        ))
        db.commit()
    with pytest.raises(RuntimeError, match="Retire resumable upload clients"):
        command.downgrade(config, "e6480b1d9a72")
    with engine.begin() as db:
        assert db.execute(text("SELECT count(*) FROM offline_uploads")).scalar_one() == 1
        db.execute(text("DELETE FROM offline_uploads"))
    command.downgrade(config, "e6480b1d9a72")
    assert "offline_uploads" not in inspect(engine).get_table_names()
    with pytest.raises(RuntimeError, match="Retain operation receipts"):
        command.downgrade(config, "e6480ac93d25")
    with engine.begin() as db:
        assert db.execute(text("SELECT count(*) FROM offline_operations")).scalar_one() == 1
        assert db.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        db.execute(text("DELETE FROM users"))
        assert db.execute(text("SELECT count(*) FROM offline_operations")).scalar_one() == 0
    command.downgrade(config, "e6480ac93d25")
    assert "offline_operations" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
