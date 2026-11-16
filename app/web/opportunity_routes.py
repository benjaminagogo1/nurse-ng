"""Member-owned saved opportunities, matching preferences and reminders."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.jobs import Job
from app.models.opportunities import SavedOpportunity
from app.models.user import User
from app.services import opportunity_watch as watch
from app.services.job_aliases import retained_job
from app.services.jobs import JOB_TYPE_LABELS, JobError, job_card, open_job_condition
from app.services.recruitment_fetch import in_scope
from app.services.vacancies import collector_authorized
from app.web.deps import require_user, verify_csrf
from app.web.feedback import message, redirect_feedback, render_error
from app.web.templating import render

router = APIRouter(tags=["opportunities"])


def preference_context(db, user, values=None):
    choice = watch.preferences(db, user)
    return {
        "user": user,
        "title": "Opportunity alerts",
        "job_types": JOB_TYPE_LABELS,
        "values": values
        if values is not None
        else {
            "keyword": choice.keyword if choice else "",
            "location": choice.location if choice else "",
            "job_type": choice.job_type if choice else "",
            "country_code": choice.country_code if choice else "NG",
            "enabled": choice.enabled if choice else False,
        },
    }


@router.get("/jobs/preferences")
def preferences(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    return render(request, "jobs/preferences.html", preference_context(db, user))


@router.post("/jobs/preferences")
def update_preferences(
    request: Request,
    keyword: str = Form(""),
    location: str = Form(""),
    job_type: str = Form(""),
    # An empty selection means all countries; keep it when FastAPI applies defaults.
    country_code: str = Form(""),
    enabled: bool = Form(False),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    values = dict(
        keyword=keyword,
        location=location,
        job_type=job_type,
        country_code=country_code,
        enabled=enabled,
    )
    try:
        watch.save_preferences(db, user, **values)
    except JobError as exc:
        return render_error(
            request,
            "jobs/preferences.html",
            preference_context(db, user, values),
            message("Preferences weren't saved", str(exc), tone="error"),
        )
    return redirect_feedback(
        request,
        "/jobs/preferences",
        message(
            "Opportunity preferences saved",
            "View your matches now. Alerts cover new opportunities that match these choices.",
        ),
    )


@router.get("/jobs/matches")
def matches(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    jobs = watch.matching_jobs(db, user)
    return render(
        request,
        "jobs/saved.html",
        {
            "user": user,
            "title": "For you",
            "matching": True,
            "jobs": [{"job": job_card(job), "saved": None} for job in jobs],
            "saved_job_ids": watch.saved_ids(db, user, [job.id for job in jobs]),
            "more": False,
            "page_number": 1,
        },
    )


@router.get("/jobs/saved")
def saved(
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(SavedOpportunity, Job)
        .join(Job)
        .where(SavedOpportunity.user_id == user.id)
        .order_by(SavedOpportunity.created_at.desc(), Job.id.desc())
        .offset((page - 1) * 25)
        .limit(26)
    ).all()
    cards = []
    for item, job in rows[:25]:
        # Keep the private bookmark removable when a source's permission is revoked.
        available = not job.source_id or (
            collector_authorized(job.source)
            and in_scope(
                job.normalized_data.get("announcement_url", ""), job.source.vacancy_url_prefix
            )
        )
        cards.append(
            {
                "job": job_card(job) if available else {"id": job.id, "unavailable": True},
                "saved": item,
            }
        )
    return render(
        request,
        "jobs/saved.html",
        {
            "user": user,
            "title": "Saved opportunities",
            "matching": False,
            "jobs": cards,
            "saved_job_ids": {row[1].id for row in rows},
            "more": len(rows) > 25,
            "page_number": page,
        },
    )


@router.post("/jobs/{job_id}/save")
def save(
    job_id: UUID,
    request: Request,
    remind: bool = Form(False),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    job = retained_job(db, db.get(Job, job_id))
    if not job or not db.scalar(select(Job.id).where(Job.id == job.id, open_job_condition())):
        raise HTTPException(status_code=404, detail="This opportunity is no longer available.")
    watch.save_job(db, user, job, remind=remind)
    return redirect_feedback(
        request,
        f"/jobs/{job.id}",
        message(
            "Opportunity saved",
            "Find it in Saved opportunities."
            + (" We’ll remind you within 48 hours of a confirmed deadline." if remind else ""),
        ),
    )


@router.post("/jobs/{job_id}/unsave")
def unsave(
    job_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    watch.remove_saved(db, user, job_id)
    return redirect_feedback(
        request,
        "/jobs/saved",
        message(
            "Opportunity removed",
            "The saved opportunity and its deadline reminder have been removed.",
        ),
    )


@router.post("/jobs/{job_id}/reminder")
def reminder(
    job_id: UUID,
    request: Request,
    remind: bool = Form(False),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    job = retained_job(db, db.get(Job, job_id))
    item = db.get(SavedOpportunity, (user.id, job.id if job else job_id))
    if item is None:
        raise HTTPException(status_code=404)
    item.remind = remind
    db.commit()
    return redirect_feedback(
        request,
        "/jobs/saved",
        message(
            "Reminder preference saved",
            "Deadline reminders are on." if remind else "Deadline reminders are off.",
        ),
    )
