"""Staff community-topic and report moderation pages."""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.community import ContentReport
from app.models.user import User
from app.services.community import (
    REPORT_REASON_LABELS,
    CommunityError,
    create_topic,
    list_open_reports,
    list_topics,
    moderate_report,
)
from app.web.deps import require_staff, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/moderation", tags=["moderation"])


def _context(db: Session, *, error: str | None = None) -> dict[str, object]:
    return {
        "title": "Community moderation",
        "reports": list_open_reports(db),
        "topics": list_topics(db, active_only=False),
        "reason_labels": REPORT_REASON_LABELS,
        "error": error,
    }


@router.get("")
def moderation_queue(
    request: Request,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> Response:
    return render(
        request,
        "moderation/queue.html",
        {"user": user, **_context(db)},
    )


@router.post("/topics")
def add_topic(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    try:
        create_topic(db, user, name=name, description=description)
    except CommunityError as exc:
        return render(
            request,
            "moderation/queue.html",
            {"user": user, **_context(db, error=str(exc))},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return redirect_feedback(
        request, "/moderation",
        message(
            'Topic created',
            'The new topic is available to the community.',
        ),
    )


@router.post("/reports/{report_id}")
def review_report(
    request: Request,
    report_id: str,
    action: str = Form(""),
    note: str = Form(""),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    try:
        identifier = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    report = db.get(ContentReport, identifier)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        moderate_report(db, user, report, action=action, note=note)
    except CommunityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return redirect_feedback(
        request, "/moderation",
        message(
            'Report reviewed',
            'Your moderation decision has been saved.',
        ),
    )
