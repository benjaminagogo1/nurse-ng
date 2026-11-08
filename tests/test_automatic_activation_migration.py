"""Preserve staff decisions and pending candidates through the activation migration."""

import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.recruitment import initialize_discovery


def test_automatic_activation_upgrade_preserves_data_and_staff_control(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'activation.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with Session(engine) as db:
        initialize_discovery(db)
    command.downgrade(config, "49b37f820e16")
    with engine.begin() as connection:
        sources = Table("recruitment_sources", MetaData(), autoload_with=connection)
        initial_ids = {row["id"] for row in connection.execute(sources.select()).mappings()}
        original = dict(connection.execute(sources.select().where(
            sources.c.original_url == "https://lshsc.ng/recruitment",
        )).mappings().one())
        for status in ("approved", "rejected", "revoked", "pending"):
            item = {**original, "id": uuid.uuid4().hex, "url_key": uuid.uuid4().hex,
                    "original_url": f"https://example.org/{status}", "verification_status": status}
            connection.execute(sources.insert().values(**item))
            if status == "pending":
                events = Table("recruitment_source_events", MetaData(), autoload_with=connection)
                connection.execute(events.insert().values(
                    id=uuid.uuid4().hex, source_id=item["id"], kind="reopen", reference_url="",
                    details={"note": "Staff investigation"}, created_at=datetime.now(UTC),
                ))
        before = [dict(row) for row in connection.execute(sources.select()).mappings()]
        history = connection.execute(text("SELECT * FROM recruitment_source_events")).all()
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        sources = Table("recruitment_sources", MetaData(), autoload_with=connection)
        actual = {row["id"]: dict(row) for row in connection.execute(sources.select()).mappings()}
        for row in before:
            assert {key: actual[row["id"]][key] for key in row} == row
            expected = "" if row["id"] in initial_ids else "staff"
            assert actual[row["id"]]["approval_mode"] == expected
            assert actual[row["id"]]["activation_review"] == {}
        assert connection.execute(text("SELECT * FROM recruitment_source_events")).all() == history
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    command.downgrade(config, "49b37f820e16")
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as connection:
        connection.execute(text("UPDATE recruitment_sources SET approval_mode = 'automatic'"))
    with pytest.raises(RuntimeError, match="automatically activated"):
        command.downgrade(config, "49b37f820e16")
    engine.dispose()
