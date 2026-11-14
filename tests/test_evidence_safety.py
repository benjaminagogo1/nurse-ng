"""Exercise actual parsers, scanner failure modes, quarantine, and retention retries."""

import hashlib
import os
import shlex
import sys
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.core import storage
from app.core.config import settings
from app.models.account import FileDeletion
from app.models.profile import NurseProfile
from app.models.user import User
from app.models.verification import EvidenceDocument, VerificationCase
from app.services.evidence import evidence_available, maintain_evidence
from app.services.verification import VerificationError, decide_case
from tests.helpers import document_bytes


@pytest.fixture
def private_store(tmp_path, monkeypatch):
    root = tmp_path / "private"
    scanner = tmp_path / "scanner.py"
    scanner.write_text("import sys\nfrom pathlib import Path\n"
                       "data = Path(sys.argv[-1]).read_bytes()\n"
                       "sys.exit(1 if b'EICAR-test-marker' in data else 0)")
    monkeypatch.setattr(settings, "evidence_dir", str(root))
    monkeypatch.setattr(settings, "evidence_scan_command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(scanner))}")
    return root


@pytest.mark.parametrize("kind,expected", [("JPEG", "image/jpeg"), ("PNG", "image/png"),
                                          ("PDF", "application/pdf")])
def test_valid_files_are_parsed_scanned_and_stored_privately(private_store, kind, expected):
    data = document_bytes(kind)
    name, content_type, size, digest = storage.save_evidence(data)
    assert content_type == expected and size == len(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert (private_store / name).read_bytes() == data
    assert private_store.stat().st_mode & 0o777 == 0o700
    assert (private_store / name).stat().st_mode & 0o777 == 0o600
    assert list(private_store.iterdir()) == [private_store / name]


@pytest.mark.parametrize("data", [b"%PDF-1.4\nnot a document", b"\xff\xd8\xffjunk",
                                  b"\x89PNG\r\n\x1a\nnot an image"])
def test_magic_bytes_do_not_make_a_valid_document(private_store, data):
    with pytest.raises(storage.EvidenceStorageError, match="complete JPEG"):
        storage.save_evidence(data)
    assert list(private_store.iterdir()) == []


@pytest.mark.parametrize("feature", ["javascript", "attachment", "password", "too_many_pages"])
def test_active_encrypted_and_oversized_pdfs_are_rejected(private_store, feature):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    if feature == "javascript":
        writer.add_js("app.alert('test');")
    elif feature == "attachment":
        writer.add_attachment("embedded.txt", b"inert test")
    elif feature == "password":
        writer.encrypt("password")
    else:
        for _ in range(25):
            writer.add_blank_page(width=300, height=400)
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(storage.EvidenceStorageError):
        storage.save_evidence(stream.getvalue())
    assert list(private_store.iterdir()) == []


@pytest.mark.parametrize("failure", ["missing", "error", "timeout", "infected"])
def test_scanner_failure_never_releases_a_file(private_store, monkeypatch, failure):
    data = document_bytes("JPEG")
    if failure == "missing":
        monkeypatch.setattr(settings, "evidence_scan_command", "/nonexistent/scanner")
    elif failure in {"error", "timeout"}:
        code = "import sys; sys.exit(2)" if failure == "error" else "import time; time.sleep(5)"
        monkeypatch.setattr(settings, "evidence_scan_command",
                            f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}")
        monkeypatch.setattr(settings, "evidence_scan_timeout_seconds", 1)
    else:
        data += b"EICAR-test-marker"
    with pytest.raises(storage.EvidenceStorageError):
        storage.save_evidence(data)
    assert list(private_store.iterdir()) == []


@pytest.fixture
def legacy_case(db_session, private_store):
    user = User(phone="+2348011111111", hashed_password="unused", full_name="Nurse")
    reviewer = User(phone="+2348022222222", hashed_password="unused", is_staff=True)
    db_session.add_all([user, reviewer])
    db_session.flush()
    profile = NurseProfile(user_id=user.id, display_name="Nurse", professional_status="student")
    db_session.add(profile)
    db_session.flush()
    name, content_type, size, digest = storage.save_evidence(document_bytes("JPEG"))
    case = VerificationCase(profile_id=profile.id, registration_number="NMCN/12345")
    case.evidence = [EvidenceDocument(kind="licence", original_filename="private-name.jpg",
                                     storage_name=name, content_type=content_type,
                                     size_bytes=size, sha256=digest)]
    db_session.add(case)
    db_session.commit()
    return case, reviewer


def test_legacy_evidence_and_tampering_block_review(db_session, legacy_case):
    case, reviewer = legacy_case
    document = case.evidence[0]
    assert not evidence_available(document)
    with pytest.raises(VerificationError, match="document checks"):
        decide_case(db_session, case=case, reviewer=reviewer, approve=True, note="Checked")
    assert maintain_evidence(db_session)["checked"] == 1
    assert evidence_available(document)
    storage.evidence_path(document.storage_name).write_bytes(b"tampered")
    assert not evidence_available(document)


def test_scanner_outage_keeps_legacy_evidence_pending(db_session, legacy_case, monkeypatch):
    case, _ = legacy_case
    monkeypatch.setattr(settings, "evidence_scan_command", "/nonexistent/scanner")
    assert maintain_evidence(db_session)["scan_unavailable"]
    assert case.evidence[0].scan_status == "pending"
    assert not evidence_available(case.evidence[0])


def test_expiry_blocks_access_before_cleanup_and_retries_failed_deletions(
    db_session, legacy_case, monkeypatch,
):
    case, _ = legacy_case
    document = case.evidence[0]
    maintain_evidence(db_session)
    case.created_at = datetime.now(UTC) - timedelta(
        days=settings.evidence_pending_retention_days + 1
    )
    db_session.commit()
    assert not evidence_available(document)
    path = storage.evidence_path(document.storage_name)
    report = maintain_evidence(db_session, dry_run=True)
    assert report["expired"] == 1 and path.exists() and document.purged_at is None
    real_unlink = Path.unlink

    def failed_unlink(self, *args, **kwargs):
        if self == path:
            raise OSError("Synthetic filesystem outage")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failed_unlink)
    assert maintain_evidence(db_session)["removed"] == 0
    assert document.purged_at and case.status == "expired" and case.registration_number == ""
    assert document.original_filename == ""
    assert db_session.scalar(select(FileDeletion)) is not None
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert maintain_evidence(db_session)["removed"] == 1
    assert not path.exists() and db_session.scalar(select(FileDeletion)) is None


def test_decision_retention_and_orphan_grace_period(db_session, legacy_case, private_store):
    case, _ = legacy_case
    case.status = "approved"
    case.decided_at = datetime.now(UTC) - timedelta(days=settings.evidence_retention_days + 1)
    db_session.commit()
    old = private_store / ".quarantine-old"
    fresh = private_store / ".quarantine-fresh"
    old.write_bytes(b"inert")
    fresh.write_bytes(b"inert")
    timestamp = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(old, (timestamp, timestamp))
    report = maintain_evidence(db_session)
    assert report["expired"] == report["orphaned"] == 1
    assert case.status == "approved"
    assert not old.exists() and fresh.exists()


def test_missing_legacy_document_is_recorded_without_claiming_a_scan(db_session, legacy_case):
    case, _ = legacy_case
    document = case.evidence[0]
    storage.evidence_path(document.storage_name).unlink()
    report = maintain_evidence(db_session)
    assert report['missing'] == 1 and report['checked'] == 0
    assert document.scan_status == 'missing' and not evidence_available(document)
