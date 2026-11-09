"""The tour migration preserves accounts and does not manufacture past preferences."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import enable_sqlite_foreign_keys
from app.models.user import User
from app.services.tours import offer_on_sign_in
from tests.test_migrations import historical_user


def test_tour_upgrade_preserves_accounts_and_guards_preference_downgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'tour-migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "d537f982ac14")
    engine = create_engine(url)
    enable_sqlite_foreign_keys(engine)
    with Session(engine) as db:
        user_id = historical_user(
            db, phone="+2348012345678", hashed_password="historical-hash",
        ).id
        db.commit()
        before = list(db.execute(text("SELECT * FROM users")))
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        assert list(db.execute(text("SELECT * FROM users"))) == before
        assert db.scalar(text("SELECT count(*) FROM user_tours")) == 0
        assert offer_on_sign_in(db, db.get(User, user_id)) is True
    with pytest.raises(RuntimeError, match="Tour preferences exist"):
        command.downgrade(config, "d537f982ac14")
    with engine.begin() as db:
        assert db.execute(text("SELECT count(*) FROM user_tours")).scalar_one() == 1
        assert db.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        db.execute(text("DELETE FROM users"))
        assert db.execute(text("SELECT count(*) FROM user_tours")).scalar_one() == 0
    command.downgrade(config, "d537f982ac14")
    assert "user_tours" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
