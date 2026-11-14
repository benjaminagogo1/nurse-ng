"""Restoration must preserve database/file references and refuse unsafe inputs."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.services.backups import BackupError, create_backup, prune_backups, restore_backup


@pytest.fixture
def backup_source(tmp_path, monkeypatch):
    path = tmp_path / "live.db"
    engine = create_engine("sqlite:///" + str(path))
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + str(path))
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    for key in ("avatar_dir", "community_media_dir", "evidence_dir"):
        directory = tmp_path / key
        directory.mkdir()
        monkeypatch.setattr(settings, key, str(directory))
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('synthetic-revision')")
    return path


def evidence_fixture(path, at):
    name = "a" * 32
    data = b"private synthetic evidence"
    from sqlalchemy.orm import Session

    from app.models.profile import NurseProfile
    from app.models.user import User
    from app.models.verification import EvidenceDocument, VerificationCase

    engine = create_engine("sqlite:///" + str(path))
    with Session(engine) as db:
        user = User(phone="+2348000000000", hashed_password="unused")
        db.add(user)
        db.flush()
        profile = NurseProfile(user_id=user.id, display_name="Backup test")
        db.add(profile)
        db.flush()
        case = VerificationCase(profile_id=profile.id, registration_number="TEST", created_at=at)
        db.add(case)
        db.flush()
        db.add(
            EvidenceDocument(
                case_id=case.id,
                kind="licence",
                storage_name=name,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                content_type="application/pdf",
            )
        )
        db.commit()
    engine.dispose()
    (Path(settings.evidence_dir) / name).write_bytes(data)
    return name, data


def test_live_database_and_private_evidence_roundtrip(backup_source, tmp_path):
    at = datetime.now(UTC)
    name, data = evidence_fixture(backup_source, at)
    backup = create_backup(at=at)
    destination = tmp_path / "restored"
    result = restore_backup(backup["backup"], destination)
    assert result["table_counts"] == backup["table_counts"]
    assert result["revisions"] == ["synthetic-revision"]
    assert result["integrity"] == result["foreign_keys"] == "ok"
    assert (destination / "evidence" / name).read_bytes() == data
    assert (destination / "database.sqlite3").stat().st_mode & 0o777 == 0o600
    assert destination.stat().st_mode & 0o777 == 0o700
    with pytest.raises(BackupError, match="must not exist"):
        restore_backup(backup["backup"], destination)


def test_corrupt_or_missing_upload_never_produces_success(backup_source, tmp_path):
    name, _ = evidence_fixture(backup_source, datetime.now(UTC))
    file = Path(settings.evidence_dir) / name
    file.write_bytes(b"changed")
    with pytest.raises(BackupError, match="size/digest"):
        create_backup()
    assert not list(Path(settings.backup_dir).glob("backup-*"))
    file.unlink()
    with pytest.raises(FileNotFoundError):
        create_backup()


def test_restore_detects_corruption_without_publishing_destination(backup_source, tmp_path):
    backup = create_backup()
    database = Path(backup["backup"]) / "database.sqlite3"
    with database.open("ab") as output:
        output.write(b"corruption")
    with pytest.raises(BackupError, match="size/digest"):
        restore_backup(backup["backup"], tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_retention_is_capped_by_evidence_expiry(backup_source, tmp_path):
    at = datetime.now(UTC)
    evidence_fixture(
        backup_source, at - timedelta(days=settings.evidence_pending_retention_days - 1)
    )
    backup = create_backup(at=at)
    assert datetime.fromisoformat(backup["expires_at"]) == at + timedelta(days=1)
    with pytest.raises(BackupError, match="expired"):
        restore_backup(backup["backup"], tmp_path / "restored", at=at + timedelta(days=2))
    unrelated = Path(settings.backup_dir) / "manual-archive"
    unrelated.mkdir()
    assert prune_backups(Path(settings.backup_dir), at=at + timedelta(days=2)) == 1
    assert unrelated.exists()


def test_manifest_traversal_and_upload_symlinks_are_refused(backup_source, tmp_path):
    backup = create_backup()
    manifest = Path(backup["backup"]) / "manifest.json"
    content = json.loads(manifest.read_text())
    content["files"]["../escape"] = {"size": 0, "sha256": ""}
    manifest.write_text(json.dumps(content))
    with pytest.raises(BackupError, match="manifest"):
        restore_backup(backup["backup"], tmp_path / "restored")
    # A private upload reference must not allow copying an arbitrary local file.
    name, _ = evidence_fixture(backup_source, datetime.now(UTC))
    file = Path(settings.evidence_dir) / name
    file.unlink()
    file.symlink_to(backup_source)
    with pytest.raises(BackupError, match="symbolic"):
        create_backup(root=tmp_path / "other-backups")


def test_preexisting_document_loss_remains_explicit_after_restore(backup_source, tmp_path):
    name, _ = evidence_fixture(backup_source, datetime.now(UTC))
    (Path(settings.evidence_dir) / name).unlink()
    with sqlite3.connect(backup_source) as db:
        db.execute("UPDATE evidence_documents SET scan_status='missing'")
    backup = create_backup()
    result = restore_backup(backup['backup'], tmp_path / 'restored')
    assert backup['unavailable_evidence'] == result['unavailable_evidence'] == 1
    assert not (tmp_path / 'restored' / 'evidence' / name).exists()
