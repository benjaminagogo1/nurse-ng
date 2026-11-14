"""Document-review workflow.

A nurse submits an NMCN (Nursing and Midwifery Council of Nigeria) licence or
certificate and a government-issued identity document. A staff reviewer
inspects both, matches the names, and approves or rejects. Approval supports
the label "document reviewed" only; it never claims source confirmation
(DECISIONS L47-L52).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.storage import (
    EvidenceStorageError,
    delete_evidence,
    save_evidence,
)
from app.models.profile import NurseProfile
from app.models.user import User
from app.models.verification import (
    CaseStatus,
    EvidenceAccess,
    EvidenceDocument,
    EvidenceKind,
    VerificationCase,
)

MAX_REGISTRATION_NUMBER = 40
MAX_DECISION_NOTE = 2000
_REGISTRATION_NUMBER_RE = re.compile(r"[A-Za-z0-9/ -]{3,40}")


class VerificationError(ValueError):
    """A submission or decision the user can correct."""


@dataclass(frozen=True)
class EvidenceUpload:
    data: bytes
    filename: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clean_registration_number(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise VerificationError("Enter your NMCN registration number.")
    if len(cleaned) > MAX_REGISTRATION_NUMBER or not _REGISTRATION_NUMBER_RE.fullmatch(
        cleaned
    ):
        raise VerificationError(
            "Registration numbers use letters, digits, spaces, hyphens, or slashes."
        )
    return cleaned


def _clean_filename(value: str) -> str:
    """Keep the basename only; the name is display text, never a path."""
    return (value or "").replace("\\", "/").rsplit("/", 1)[-1][:255]


_KIND_LABELS = {
    EvidenceKind.LICENCE: "Licence or certificate",
    EvidenceKind.GOVERNMENT_ID: "ID document",
    EvidenceKind.NURSING_CERTIFICATE: "Nursing certificate",
    EvidenceKind.ADDITIONAL_CERT: "Additional certification",
}


def _store_upload(kind: EvidenceKind, upload: EvidenceUpload) -> EvidenceDocument:
    try:
        storage_name, content_type, size, digest = save_evidence(upload.data)
    except EvidenceStorageError as exc:
        raise VerificationError(f"{_KIND_LABELS[kind]}: {exc}") from None
    return EvidenceDocument(
        kind=kind.value,
        original_filename=_clean_filename(upload.filename),
        storage_name=storage_name,
        content_type=content_type,
        size_bytes=size,
        sha256=digest,
        scan_status="clean",
        scanned_at=_utcnow(),
    )


def submit_case(
    db: Session,
    *,
    user: User,
    profile: NurseProfile,
    registration_number: str,
    licence: EvidenceUpload,
    government_id: EvidenceUpload,
    nursing_certificate: EvidenceUpload | None = None,
    additional_certification: EvidenceUpload | None = None,
) -> VerificationCase:
    """Create a pending case with all private evidence files."""
    if profile.user_id != user.id:
        raise VerificationError("This profile does not belong to the signed-in user.")

    number = _clean_registration_number(registration_number)
    existing = db.scalar(
        select(VerificationCase.id).where(
            VerificationCase.profile_id == profile.id,
            VerificationCase.status == CaseStatus.PENDING,
        )
    )
    if existing is not None:
        raise VerificationError("You already have a review in progress.")

    uploads: list[tuple[EvidenceKind, EvidenceUpload]] = [
        (EvidenceKind.LICENCE, licence),
        (EvidenceKind.GOVERNMENT_ID, government_id),
    ]
    if nursing_certificate is not None and nursing_certificate.data:
        uploads.append((EvidenceKind.NURSING_CERTIFICATE, nursing_certificate))
    if additional_certification is not None and additional_certification.data:
        uploads.append((EvidenceKind.ADDITIONAL_CERT, additional_certification))

    stored: list[EvidenceDocument] = []
    try:
        for kind, upload in uploads:
            stored.append(_store_upload(kind, upload))
    except VerificationError:
        for document in stored:
            delete_evidence(document.storage_name)
        raise

    case = VerificationCase(
        profile_id=profile.id,
        registration_number=number,
        status=CaseStatus.PENDING,
    )
    case.evidence = stored
    db.add(case)
    try:
        db.commit()
    except Exception:
        db.rollback()
        for document in stored:
            delete_evidence(document.storage_name)
        raise VerificationError("The submission could not be saved. Try again.") from None

    db.refresh(case)
    return case

def list_cases_for_profile(db: Session, profile_id: uuid.UUID) -> list[VerificationCase]:
    return list(
        db.scalars(
            select(VerificationCase)
            .where(VerificationCase.profile_id == profile_id)
            .order_by(VerificationCase.created_at.desc())
        ).all()
    )


def has_pending_case(db: Session, profile_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(VerificationCase.id).where(
                VerificationCase.profile_id == profile_id,
                VerificationCase.status == CaseStatus.PENDING,
            )
        )
        is not None
    )


def get_case(db: Session, case_id: uuid.UUID) -> VerificationCase | None:
    return db.get(VerificationCase, case_id)


def pending_cases(db: Session) -> list[VerificationCase]:
    return list(
        db.scalars(
            select(VerificationCase)
            .where(VerificationCase.status == CaseStatus.PENDING)
            .order_by(VerificationCase.created_at.asc())
        ).all()
    )


def recent_decisions(db: Session, limit: int = 20) -> list[VerificationCase]:
    return list(
        db.scalars(
            select(VerificationCase)
            .where(VerificationCase.status != CaseStatus.PENDING)
            .order_by(VerificationCase.decided_at.desc())
            .limit(limit)
        ).all()
    )


def find_evidence(case: VerificationCase, evidence_id: uuid.UUID) -> EvidenceDocument | None:
    for document in case.evidence:
        if document.id == evidence_id:
            return document
    return None


def record_evidence_access(
    db: Session,
    *,
    evidence: EvidenceDocument,
    reviewer: User,
) -> None:
    db.add(
        EvidenceAccess(
            evidence_id=evidence.id,
            accessed_by_user_id=reviewer.id,
        )
    )
    db.commit()


def decide_case(
    db: Session,
    *,
    case: VerificationCase,
    reviewer: User,
    approve: bool,
    note: str,
) -> VerificationCase:
    """Approve or reject a pending case. Approval sets the public label date."""
    if case.status != CaseStatus.PENDING:
        raise VerificationError("This case has already been decided.")
    if case.profile.user_id == reviewer.id:
        # The label means a second person inspected the documents; a
        # self-decision would make it meaningless (DECISIONS L51).
        raise VerificationError("A reviewer cannot decide their own case.")
    if approve:
        from app.services.evidence import evidence_available

        if not case.evidence or any(not evidence_available(doc) for doc in case.evidence):
            raise VerificationError("All evidence must pass document checks before approval.")

    cleaned_note = (note or "").strip()
    if len(cleaned_note) > MAX_DECISION_NOTE:
        raise VerificationError(
            f"The decision note must be at most {MAX_DECISION_NOTE} characters."
        )
    if not approve and not cleaned_note:
        raise VerificationError("A rejection needs a reason for the nurse.")

    now = _utcnow()
    # The database owns the transition: two reviewers may both have loaded PENDING.
    # Keep the case decision and public label in this same transaction.
    changed = db.execute(
        update(VerificationCase)
        .where(VerificationCase.id == case.id, VerificationCase.status == CaseStatus.PENDING)
        .values(
            status=CaseStatus.APPROVED if approve else CaseStatus.REJECTED,
            decided_by_user_id=reviewer.id,
            decided_at=now,
            decision_note=cleaned_note,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        db.refresh(case)
        raise VerificationError("This case has already been decided. Refresh to see the decision.")
    db.refresh(case)

    if approve:
        # A prior approval stands if a later resubmission is rejected; this
        # column only moves forward on approval (DECISIONS L51).
        profile = db.scalar(
            select(NurseProfile)
            .where(NurseProfile.id == case.profile_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        reviewed_name = (profile.display_name or "").strip()
        case.reviewed_display_name = reviewed_name
        profile.document_reviewed_at = now
        profile.document_reviewed_name = reviewed_name

    db.commit()
    db.refresh(case)
    return case
