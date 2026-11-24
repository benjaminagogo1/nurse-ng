"""Legacy document checks and durable, scheduled removal of expired private evidence.

Retention removes private document objects and updates their availability.
A historical review decision may remain after its evidence expires; these are
different lifecycle records. Dry-run maintenance reports without deleting.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.core import storage
from app.core.config import settings
from app.models.verification import CaseStatus, EvidenceDocument, VerificationCase
from app.services.accounts import cleanup_account_files, queue_file_deletion


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def expires_at(case):
    if case.decided_at:
        return utc(case.decided_at) + timedelta(days=settings.evidence_retention_days)
    return utc(case.created_at) + timedelta(days=settings.evidence_pending_retention_days)


def evidence_available(document, *, at=None):
    if (document.scan_status != "clean" or not document.scanned_at or document.purged_at
            or expires_at(document.case) <= (at or datetime.now(UTC))):
        return False
    try:
        path = storage.evidence_path(document.storage_name)
        return (path.stat().st_size == document.size_bytes
                and hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256)
    except (OSError, storage.EvidenceStorageError):
        return False


def maintain_evidence(db, *, dry_run=False, limit=100, at=None):
    timestamp = at or datetime.now(UTC)
    result = {"expired": 0, "checked": 0, "rejected": 0, "missing": 0, "scan_unavailable": False,
              "orphaned": 0, "removed": 0}
    cases = list(db.scalars(select(VerificationCase).where(
        or_(
            VerificationCase.decided_at <= timestamp - timedelta(
                days=settings.evidence_retention_days),
            (VerificationCase.decided_at.is_(None)) & (
                VerificationCase.created_at <= timestamp - timedelta(
                    days=settings.evidence_pending_retention_days)),
        ),
        VerificationCase.evidence.any(EvidenceDocument.purged_at.is_(None)),
    ).order_by(VerificationCase.created_at).limit(limit).with_for_update()))
    for case in cases:
        for document in case.evidence:
            if document.purged_at:
                continue
            result["expired"] += 1
            if not dry_run:
                document.purged_at = timestamp
                document.original_filename = ""
                queue_file_deletion(db, "evidence", document.storage_name)
        if not dry_run:
            case.registration_number = ""
            if case.status == CaseStatus.PENDING:
                case.status = CaseStatus.EXPIRED
                case.decided_at = timestamp
                case.decision_note = "The review period ended. Please submit a new request."
    if not dry_run:
        db.commit()  # Persist the removal queue before touching files; failures can retry.
        result["removed"] = cleanup_account_files(db, limit=limit * 4)["removed"]

    documents = list(db.scalars(select(EvidenceDocument).where(
        EvidenceDocument.scan_status == "pending", EvidenceDocument.purged_at.is_(None)
    ).order_by(EvidenceDocument.created_at).limit(limit)))
    for document in documents:
        if dry_run:
            result["checked"] += 1
            continue
        try:
            path = storage.evidence_path(document.storage_name)
            if (path.stat().st_size > settings.evidence_max_bytes
                    or hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256):
                raise storage.EvidenceStorageError("Document integrity check failed")
            content_type = storage.validate_evidence(path)
            storage.scan_evidence(path)
        except storage.EvidenceScanUnavailable:
            result["scan_unavailable"] = True
            break
        except FileNotFoundError:
            document.scan_status = "missing"
            result["missing"] += 1
        except (OSError, storage.EvidenceStorageError):
            document.scan_status = "rejected"
            result["rejected"] += 1
        else:
            document.content_type = content_type
            document.scan_status = "clean"
            document.scanned_at = timestamp
            result["checked"] += 1
        db.commit()

    # Crash remnants have no database row. A day's grace protects active submissions.
    root = storage._root()
    names = set(db.scalars(select(EvidenceDocument.storage_name)))
    if root.exists():
        for path in root.iterdir():
            if (path.is_symlink() or not path.is_file() or path.name in names
                    or not (storage._STORAGE_NAME_RE.fullmatch(path.name)
                            or path.name.startswith(".quarantine-"))):
                continue
            if path.stat().st_mtime >= (timestamp - timedelta(days=1)).timestamp():
                continue
            result["orphaned"] += 1
            if not dry_run:
                path.unlink(missing_ok=True)
    return result
