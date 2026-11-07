"""Upgrade keeps existing employer jobs/applications; downgrade refuses lossy conversion."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recruitment import RecruitmentSource
from app.services.recruitment import collection_authorized, initialize_discovery


def test_vacancy_upgrade_preserves_employer_jobs_and_applicants(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'vacancies.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "a3310f4d2d7b")
    engine = create_engine(database_url)
    employer_id, nurse_id, job_id, application_id = [uuid.uuid4().hex for _ in range(4)]
    with engine.begin() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        for identifier, phone, role in [
            (employer_id, "+2348000000001", "employer"),
            (nurse_id, "+2348000000002", "nurse"),
        ]:
            connection.execute(
                users.insert().values(
                    id=identifier,
                    phone=phone,
                    hashed_password="historical",
                    account_type=role,
                    status="active",
                    phone_verified=False,
                    mfa_enabled=False,
                    is_active=True,
                    is_staff=False,
                )
            )
        jobs = Table("jobs", MetaData(), autoload_with=connection)
        connection.execute(
            jobs.insert().values(
                id=job_id,
                employer_user_id=employer_id,
                title="Existing registered nurse role",
                organization="Existing hospital",
                location="Lagos",
                description="Preserve this vacancy",
                job_type="full_time",
                work_mode="on_site",
                salary_min=250000,
                salary_max=350000,
                status="open",
                posted_at=datetime.now(UTC),
            )
        )
        applications = Table("job_applications", MetaData(), autoload_with=connection)
        connection.execute(
            applications.insert().values(
                id=application_id,
                job_id=job_id,
                applicant_user_id=nurse_id,
                candidate_name="Existing applicant",
                candidate_phone="+2348000000002",
                candidate_email="nurse@example.org",
                cover_note="Preserve consented details",
                status="submitted",
            )
        )
        before_job = dict(connection.execute(jobs.select()).mappings().one())
        before_application = dict(connection.execute(applications.select()).mappings().one())
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        jobs = Table("jobs", MetaData(), autoload_with=connection)
        actual = dict(connection.execute(jobs.select()).mappings().one())
        assert {key: actual[key] for key in before_job} == before_job
        assert actual["source_id"] is None and actual["country_code"] == ""
        applications = Table("job_applications", MetaData(), autoload_with=connection)
        assert (
            dict(connection.execute(applications.select()).mappings().one()) == before_application
        )
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    command.downgrade(config, "a3310f4d2d7b")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM job_applications")).scalar_one() == 1
        assert (
            connection.execute(text("SELECT cover_note FROM job_applications")).scalar_one()
            == "Preserve consented details"
        )
    command.upgrade(config, "head")
    command.check(config)
    assert "vacancy_snapshots" in inspect(engine).get_table_names()
    engine.dispose()


def test_reuse_upgrade_preserves_legacy_evidence_without_inventing_rights(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'reuse.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with Session(engine) as session:
        initialize_discovery(session)
    command.downgrade(config, "3838cd201521")
    with engine.begin() as connection:
        sources = Table("recruitment_sources", MetaData(), autoload_with=connection)
        connection.execute(
            sources.update().values(
                verification_status="approved",
                permission_status="permitted",
                collection_method="html",
                collection_adapter="jsonld",
                approval_expires_at=datetime.now(UTC) + timedelta(days=30),
                vacancy_url_prefix="https://lshsc.ng",
                deadline_timezone="Africa/Lagos",
                access_notes="Historical review finding retained",
            )
        )
        before = dict(connection.execute(sources.select()).mappings().one())
        history = connection.execute(text("SELECT * FROM recruitment_source_events")).all()
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        sources = Table("recruitment_sources", MetaData(), autoload_with=connection)
        actual = dict(connection.execute(sources.select()).mappings().one())
        assert {key: actual[key] for key in before} == before
        assert connection.execute(text("SELECT * FROM recruitment_source_events")).all() == history
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    with Session(engine) as session:
        source = session.query(RecruitmentSource).one()
        assert source.reuse_basis == source.reuse_url_prefix == ""
        assert not source.allow_collection and not source.allow_snapshot_retention
        assert not source.allow_republication and not collection_authorized(source)
        source.reuse_basis = "legal_basis"
        session.commit()
    with pytest.raises(RuntimeError, match="archive"):
        command.downgrade(config, "3838cd201521")
    assert "reuse_basis" in {
        column["name"] for column in inspect(engine).get_columns("recruitment_sources")
    }
    engine.dispose()


def test_downgrade_refuses_populated_vacancy_history_before_mutating_schema(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'refuse.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    # A synthetic snapshot is enough to require explicit archival before a downgrade.
    with Session(engine) as session:
        initialize_discovery(session)
    with engine.begin() as connection:
        snapshots = Table("vacancy_snapshots", MetaData(), autoload_with=connection)
        connection.execute(
            snapshots.insert().values(
                id=uuid.uuid4().hex,
                source_id=connection.execute(
                    text("SELECT id FROM recruitment_sources")
                ).scalar_one(),
                original_url="https://example.org",
                observed_url="https://example.org",
                content_hash="a" * 64,
                body=b"original",
                collected_at=datetime.now(UTC),
                adapter="jsonld-v1",
            )
        )
    with pytest.raises(RuntimeError, match="archive"):
        command.downgrade(config, "a3310f4d2d7b")
    assert "vacancy_events" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT body FROM vacancy_snapshots")).scalar_one()
            == b"original"
        )
    engine.dispose()
