"""Staff reviewer pages for document-review cases.

Every route requires ``is_staff``. Evidence is served only here, from the
private store, and each read is written to the access log (DECISIONS L49).
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.storage import CONTENT_TYPE_SUFFIX, EvidenceStorageError, evidence_path
from app.db.session import get_db
from app.models.user import User
from app.models.verification import EvidenceDocument
from app.services.verification import (
    VerificationError,
    decide_case,
    find_evidence,
    get_case,
    pending_cases,
    recent_decisions,
    record_evidence_access,
)
from app.web.deps import require_staff, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/review", tags=["review"])

KIND_LABELS = {
    "licence": "Licence or certificate",
    "government_id": "Government-issued ID",
    "nursing_certificate": "Nursing certificate",
    "additional_cert": "Additional certification",
}

def _case_context(case, reviewer: User, *, error: str | None = None) -> dict[str, object]:
    return {
        "title": f"Review case — {case.profile.display_name or 'Unnamed profile'}",
        "user": reviewer,
        "case": case,
        "kinds": KIND_LABELS,
        "error": error,
    }


@router.get("")
def review_queue(
    request: Request,
    reviewer: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> Response:
    return render(
        request,
        "review/queue.html",
        {
            "title": "Review queue",
            "user": reviewer,
            "pending": pending_cases(db),
            "recent": recent_decisions(db),
        },
    )


@router.get("/{case_id}")
def review_case(
    case_id: str,
    request: Request,
    reviewer: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> Response:
    case = _load_case(db, case_id)
    return render(request, "review/case.html", _case_context(case, reviewer))


@router.get("/{case_id}/evidence/{evidence_id}")
def review_evidence(
    case_id: str,
    evidence_id: str,
    reviewer: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> FileResponse:
    case = _load_case(db, case_id)
    document = _load_evidence(case, evidence_id)

    try:
        path = evidence_path(document.storage_name)
    except EvidenceStorageError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    record_evidence_access(db, evidence=document, reviewer=reviewer)
    suffix = CONTENT_TYPE_SUFFIX.get(document.content_type, "")
    return FileResponse(
        path,
        media_type=document.content_type,
        filename=f"{document.kind}{suffix}",
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@router.post("/{case_id}/decide")
def review_decision(
    case_id: str,
    request: Request,
    decision: str = Form(""),
    note: str = Form(""),
    reviewer: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    case = _load_case(db, case_id)
    if decision not in {"approve", "reject"}:
        return render(
            request,
            "review/case.html",
            _case_context(case, reviewer, error="Choose approve or reject."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        decide_case(
            db,
            case=case,
            reviewer=reviewer,
            approve=decision == "approve",
            note=note,
        )
    except VerificationError as exc:
        return render(
            request,
            "review/case.html",
            _case_context(case, reviewer, error=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return redirect_feedback(
        request, "/review",
        message(
            'Review saved',
            'Your document-review decision has been recorded.',
        ),
    )


def _load_case(db: Session, raw_id: str):
    try:
        case_id = uuid.UUID(raw_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    case = get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return case


def _load_evidence(case, raw_id: str) -> EvidenceDocument:
    try:
        evidence_id = uuid.UUID(raw_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    document = find_evidence(case, evidence_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return document
