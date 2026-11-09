"""Staff-only original records and vacancy exception review."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.services.recruitment import RecruitmentError
from app.services.vacancies import EDITABLE, record_list, review_record
from app.web.deps import require_staff, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.recruitment_routes import _load
from app.web.templating import render

router = APIRouter(prefix="/recruitment/vacancies", tags=["vacancy review"])


def detail_response(request, db, user, record, *, error=None, history_page=1, values=None):
    history = list(
        db.scalars(
            select(VacancyEvent)
            .where(VacancyEvent.record_id == record.id)
            .order_by(VacancyEvent.created_at.desc(), VacancyEvent.id.desc())
            .offset((history_page - 1) * 20)
            .limit(21)
        )
    )
    return render(
        request,
        "recruitment/vacancy.html",
        {
            "user": user,
            "record": record,
            "error": error,
            "values": values or {},
            "history": history[:20],
            "has_more": len(history) > 20,
            "history_page": history_page,
            "fields": {
                "title": "Job title",
                "employer": "Employer",
                "country": "Country code",
                "region": "State or region",
                "city": "City",
                "announcement_url": "Original vacancy URL",
                "publication_date": "Publication date",
                "closing_date": "Closing date",
                "opening_date": "Application opening date (optional)",
            },
        },
        status_code=400 if error else 200,
    )


@router.get("")
def index(
    request: Request,
    state: str = Query("pending", max_length=20),
    source_id: UUID | None = None,
    page: int = Query(1, ge=1, le=100000),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    rows, total = record_list(db, state=state, source_id=source_id, page=page)
    return render(
        request,
        "recruitment/vacancies.html",
        {
            "user": user,
            "records": rows,
            "total": total,
            "state": state,
            "source_id": source_id,
            "previous_url": str(request.url.include_query_params(page=page - 1))
            if page > 1
            else "",
            "next_url": str(request.url.include_query_params(page=page + 1))
            if page * 25 < total
            else "",
        },
    )


@router.get("/{record_id}")
def detail(
    record_id: str,
    request: Request,
    history_page: int = Query(1, ge=1, le=100000),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return detail_response(
        request, db, user, _load(db, VacancyRecord, record_id), history_page=history_page
    )


@router.get("/{record_id}/original")
def original(record_id: str, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    record = _load(db, VacancyRecord, record_id)
    snapshot = db.get(VacancySnapshot, record.snapshot_id)
    return _snapshot_response(snapshot)


@router.get("/snapshots/{snapshot_id}/original")
def snapshot_original(
    snapshot_id: str, user: User = Depends(require_staff), db: Session = Depends(get_db)
):
    return _snapshot_response(_load(db, VacancySnapshot, snapshot_id))


def _snapshot_response(snapshot):
    return Response(
        snapshot.body,
        media_type="text/plain",
        headers={
            "Content-Disposition": 'attachment; filename="source-snapshot.txt"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/{record_id}/review")
async def review(
    record_id: str,
    request: Request,
    revision: int = Form(...),
    action: str = Form(""),
    note: str = Form(""),
    reference: str = Form(""),
    employer_confirmed: bool = Form(False),
    nursing_confirmed: bool = Form(False),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    record = _load(db, VacancyRecord, record_id)
    form = await request.form()
    try:
        review_record(
            db,
            user,
            record,
            revision=revision,
            action=action,
            note=note,
            reference=reference,
            changes={key: form[key] for key in EDITABLE if key in form},
            employer_confirmed=employer_confirmed,
            nursing_confirmed=nursing_confirmed,
        )
    except RecruitmentError as exc:
        db.rollback()
        return detail_response(
            request,
            db,
            user,
            record,
            error=str(exc),
            values={key: value for key, value in form.items() if isinstance(value, str)},
        )
    return redirect_feedback(
        request, f"/recruitment/vacancies/{record.id}",
        message(
            'Opportunity review saved',
            'Your decision and any listing changes have been saved.',
        ),
    )
