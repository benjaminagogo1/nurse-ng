"""Keep historical listings, applications and evidence while withholding unreviewed access."""

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.profile import NurseProfile
from app.models.user import User
from app.models.verification import VerificationCase


def test_existing_records_survive_without_receiving_approval(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "e6480d3fb942")
    engine = create_engine(url)
    with Session(engine) as db:
        employer = User(phone="+2348011111111", hashed_password="keep-employer-password",
                        account_type="employer")
        nurse = User(phone="+2348022222222", hashed_password="keep-nurse-password")
        db.add_all([employer, nurse])
        db.flush()
        profile = NurseProfile(user_id=nurse.id, display_name="Original Nurse",
                               professional_status="student")
        db.add(profile)
        db.flush()
        case = VerificationCase(profile_id=profile.id, registration_number="NMCN/12345")
        db.add(case)
        db.flush()
        meta = MetaData()
        jobs = Table("jobs", meta, autoload_with=db.connection())
        applications = Table("job_applications", meta, autoload_with=db.connection())
        evidence = Table("evidence_documents", meta, autoload_with=db.connection())
        job_id, application_id, evidence_id = (uuid.uuid4().hex for _ in range(3))
        db.execute(jobs.insert().values(
            id=job_id, employer_user_id=employer.id.hex, title="Existing job",
            organization="Original Hospital", location="Lagos", job_type="full_time",
            work_mode="on_site", description="Original description", status="open",
        ))
        db.execute(applications.insert().values(
            id=application_id, job_id=job_id, applicant_user_id=nurse.id.hex,
            candidate_name="Original Nurse", candidate_phone=nurse.phone,
            candidate_email="original@example.org", cover_note="Private note", status="submitted",
        ))
        db.execute(evidence.insert().values(
            id=evidence_id, case_id=case.id.hex, kind="licence", original_filename="original.pdf",
            storage_name="a" * 32, content_type="application/pdf", size_bytes=53, sha256="b" * 64,
        ))
        db.commit()
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT employer_organization_id FROM jobs")).scalar() is None
        assert conn.execute(text("SELECT title FROM jobs")).scalar_one() == "Existing job"
        note = conn.execute(text("SELECT cover_note FROM job_applications")).scalar_one()
        assert note == "Private note"
        row = conn.execute(text(
            "SELECT scan_status, scanned_at, purged_at, storage_name FROM evidence_documents"
        )).one()
        assert tuple(row) == ("pending", None, None, "a" * 32)
        assert conn.execute(text("SELECT count(*) FROM employer_memberships")).scalar_one() == 0
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
    command.downgrade(config, "e6480d3fb942")
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM job_applications")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM evidence_documents")).scalar_one() == 1
    engine.dispose()
