"""Private source discovery and approval screens. Requests never fetch websites."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.recruitment import DiscoverySchedule, DiscoveryTask, RecruitmentSource, SourceEvent
from app.models.user import User
from app.models.vacancies import VacancyRecord, VacancySnapshot
from app.services import recruitment as registry
from app.services.vacancies import activation_blockers, configure_collector
from app.web.deps import require_staff, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render
from app.web.urls import page_url

router = APIRouter(prefix="/recruitment", tags=["recruitment sources"])


def _load(db, model, identifier):
    try:
        record = db.get(model, UUID(identifier))
    except ValueError:
        record = None
    if record is None:
        raise HTTPException(404)
    return record


def _dashboard(
    request, db, user, *, error=None, values=None, query="", status="", country="", page=1
):
    sources, total = registry.list_sources(
        db,
        query=query,
        status=status,
        country_code=country,
        page=page,
    )
    from app.models.jobs import Job
    from app.services.jobs import open_job_condition
    from app.services.worker_health import snapshot, worker_names

    try:
        with db.begin_nested():
            workers = snapshot(db, worker_names(settings.required_workers) or ("recruitment",))
    except SQLAlchemyError:
        workers = []
    pending_records = db.scalar(select(func.count()).select_from(VacancyRecord).where(
        VacancyRecord.state == "pending"
    ))
    public_jobs = db.scalar(select(func.count()).select_from(Job).where(open_job_condition()))
    oldest_waiting = db.scalar(select(func.min(DiscoveryTask.created_at)).where(
        DiscoveryTask.status == "queued"
    ))
    return render(
        request,
        "recruitment/index.html",
        {
            "user": user,
            "sources": sources,
            "total": total,
            "categories": registry.CATEGORIES,
            "schedules": list(
                db.scalars(select(DiscoverySchedule).order_by(DiscoverySchedule.name))
            ),
            "tasks": list(
                db.scalars(
                    select(DiscoveryTask)
                    .order_by(DiscoveryTask.created_at.desc(), DiscoveryTask.id.desc())
                    .limit(20)
                )
            ),
            "counts": registry.task_counts(db),
            "workers": workers,
            "pending_records": pending_records,
            "public_jobs": public_jobs,
            "oldest_waiting": oldest_waiting,
            "error": error,
            "values": values or {},
            "query": query,
            "status": status,
            "country": country,
            "page_number": page,
            "previous_url": page_url(request, page=page - 1)
            if page > 1
            else "",
            "next_url": page_url(request, page=page + 1)
            if page * 25 < total
            else "",
            "search_enabled": bool(
                settings.recruitment_searxng_urls
                or (
                    settings.recruitment_search_key
                    and settings.recruitment_search_permission_reference
                )
            ),
            "brave_enabled": bool(
                settings.recruitment_search_key and settings.recruitment_search_permission_reference
            ),
        },
        status_code=400 if error else 200,
    )


def _detail(request, db, user, source, *, error=None, values=None, history_page=1):
    from app.services.recruitment_indexing import configuration

    try:
        _, index_scope = configuration(source)
    except ValueError:
        index_scope = ""
    history = list(
        db.scalars(
            select(SourceEvent)
            .where(SourceEvent.source_id == source.id)
            .order_by(SourceEvent.created_at.desc(), SourceEvent.id.desc())
            .offset((history_page - 1) * 25)
            .limit(26)
        )
    )
    return render(
        request,
        "recruitment/source.html",
        {
            "user": user,
            "source": source,
            "categories": registry.CATEGORIES,
            "checks": registry.CHECKS,
            "methods": registry.METHODS,
            "reuse_bases": registry.REUSE_BASES,
            "reuse_rights": registry.REUSE_RIGHTS,
            "activation_blockers": activation_blockers(source),
            "history": history[:25],
            "snapshots": list(
                db.scalars(
                    select(VacancySnapshot)
                    .where(VacancySnapshot.source_id == source.id)
                    .order_by(VacancySnapshot.collected_at.desc())
                    .limit(5)
                )
            ),
            "history_page": history_page,
            "has_more": len(history) > 25,
            "current_approval": registry.approval_current(source),
            "default_expiry": (registry.now() + timedelta(days=90)).date().isoformat(),
            "default_index_scope": index_scope,
            "error": error,
            "values": values or {},
        },
        status_code=400 if error else 200,
    )


@router.get("")
def index(
    request: Request,
    q: str = Query("", max_length=200),
    status: str = Query("", max_length=20),
    country: str = Query("", max_length=2),
    page: int = Query(1, ge=1, le=100000),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return _dashboard(request, db, user, query=q, status=status, country=country, page=page)


@router.post("/sources")
def register(
    request: Request,
    name: str = Form(""),
    category: str = Form("unconfirmed"),
    country_code: str = Form(""),
    location: str = Form(""),
    website_url: str = Form(""),
    source_url: str = Form(""),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    values = dict(
        name=name,
        category=category,
        country_code=country_code,
        location=location,
        website_url=website_url,
        source_url=source_url,
    )
    try:
        source = registry.register_manual_source(db, user, **values)
    except registry.RecruitmentError as exc:
        db.rollback()
        return _dashboard(request, db, user, error=str(exc), values=values)
    return redirect_feedback(
        request, f"/recruitment/sources/{source.id}",
        message(
            'Source registered',
            'The source is ready for evidence checks.',
        ),
    )


@router.post("/schedules")
def schedule(
    request: Request,
    name: str = Form(""),
    provider: str = Form("ror"),
    country_code: str = Form(""),
    query: str = Form(""),
    interval_hours: int = Form(24),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        registry.add_schedule(
            db,
            user,
            name=name,
            provider=provider,
            country_code=country_code,
            query=query,
            interval_hours=interval_hours,
        )
    except registry.RecruitmentError as exc:
        db.rollback()
        return _dashboard(request, db, user, error=str(exc))
    return redirect_feedback(
        request, "/recruitment#schedules",
        message(
            'Schedule created',
            'The worker will use this discovery schedule.',
        ),
    )


@router.post("/schedules/{schedule_id}")
def toggle_schedule(
    request: Request,
    schedule_id: str,
    enabled: bool = Form(False),
    adapter: str = Form("jsonld"),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    item = _load(db, DiscoverySchedule, schedule_id)
    registry.set_schedule_enabled(db, user, item, enabled=enabled)
    return redirect_feedback(
        request, "/recruitment#schedules",
        message(
            'Schedule updated',
            'The discovery schedule now uses your selected setting.',
        ),
    )


@router.get("/coverage")
def coverage_page(
    request: Request, user: User = Depends(require_staff), db: Session = Depends(get_db)
):
    from app.services.opportunity_coverage import coverage

    return render(
        request,
        "recruitment/coverage.html",
        {
            "user": user,
            "title": "Nigerian opportunity coverage",
            "coverage": coverage(db),
        },
    )


@router.get("/sources/{source_id}")
def detail(
    source_id: str,
    request: Request,
    history_page: int = Query(1, ge=1, le=100000),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return _detail(
        request, db, user, _load(db, RecruitmentSource, source_id), history_page=history_page
    )


@router.post("/sources/{source_id}/review")
async def review(
    source_id: str,
    request: Request,
    revision: int = Form(...),
    action: str = Form(""),
    note: str = Form(""),
    method: str = Form("unconfirmed"),
    index_scope: str = Form(""),
    expires_at: str = Form(""),
    licensing_applicability: str = Form("required"),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    source = _load(db, RecruitmentSource, source_id)
    form = await request.form()
    values = {key: value for key, value in form.items() if isinstance(value, str)}
    try:
        expiry = None
        if action in {"approve", "approve_index"}:
            try:
                expiry = datetime.strptime(expires_at, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                raise registry.RecruitmentError("Choose a valid review expiry date.") from None
        registry.review_source(
            db,
            user,
            source,
            revision=revision,
            action=action,
            note=note,
            method=method,
            index_scope=index_scope,
            expires_at=expiry,
            licensing_applicability=licensing_applicability,
            checks={
                key: {"note": values.get(f"{key}_note", ""), "url": values.get(f"{key}_url", "")}
                for key in registry.CHECKS
            },
            reuse={
                "basis": values.get("reuse_basis", ""),
                "url_prefix": values.get("reuse_url_prefix", ""),
                **{right: values.get(right) == "true" for right in registry.REUSE_RIGHTS},
            },
        )
    except registry.RecruitmentError as exc:
        db.rollback()
        return _detail(request, db, user, source, error=str(exc), values=values)
    return redirect_feedback(
        request, f"/recruitment/sources/{source.id}",
        message(
            'Source approved and collection enabled'
            if action == 'approve_index' else 'Source review saved',
            'The worker will check this source and publish valid vacancies.'
            if action == 'approve_index' else 'Your decision has been recorded.',
        ),
    )


@router.post("/sources/{source_id}/organisation")
def organisation(
    source_id: str,
    request: Request,
    revision: int = Form(...),
    name: str = Form(""),
    category: str = Form("unconfirmed"),
    country_code: str = Form(""),
    location: str = Form(""),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    source = _load(db, RecruitmentSource, source_id)
    try:
        registry.update_organization(
            db,
            user,
            source,
            revision=revision,
            name=name,
            category=category,
            country_code=country_code,
            location=location,
        )
    except registry.RecruitmentError as exc:
        db.rollback()
        return _detail(request, db, user, source, error=str(exc))
    return redirect_feedback(
        request, f"/recruitment/sources/{source.id}",
        message(
            'Organisation updated',
            'The organisation details have been saved.',
        ),
    )


@router.post("/sources/{source_id}/check")
def check(
    source_id: str,
    request: Request,
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    source = _load(db, RecruitmentSource, source_id)
    try:
        registry.request_inspection(db, user, source)
    except registry.RecruitmentError as exc:
        db.rollback()
        return _detail(request, db, user, source, error=str(exc))
    return redirect_feedback(
        request, f"/recruitment/sources/{source.id}",
        message(
            'Inspection queued',
            'The worker will check this source. Return here for the result.',
        ),
    )


@router.post("/sources/{source_id}/collector")
def collector(
    source_id: str,
    request: Request,
    revision: int = Form(...),
    enabled: bool = Form(False),
    adapter: str = Form("jsonld"),
    url_prefix: str = Form(""),
    timezone: str = Form(""),
    note: str = Form(""),
    reference: str = Form(""),
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    source = _load(db, RecruitmentSource, source_id)
    try:
        configure_collector(
            db,
            user,
            source,
            revision=revision,
            enabled=enabled,
            adapter=adapter,
            url_prefix=url_prefix,
            timezone=timezone,
            note=note,
            reference=reference,
        )
    except registry.RecruitmentError as exc:
        db.rollback()
        return _detail(request, db, user, source, error=str(exc))
    return redirect_feedback(
        request, f"/recruitment/sources/{source.id}",
        message(
            'Collector updated',
            'The source collector configuration has been saved.',
        ),
    )
