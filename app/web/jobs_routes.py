"""Job listings, employer job posting, and the employer landing page."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.jobs import Job, JobApplication, JobStatus
from app.models.opportunities import SavedOpportunity
from app.models.user import AccountType, User
from app.services.employers import approved_organizations, authorized
from app.services.job_aliases import retained_job
from app.services.jobs import (
    APPLICATION_STATUS_LABELS,
    JOB_TYPE_LABELS,
    WORK_MODE_LABELS,
    JobError,
    application_for_job,
    apply_for_job,
    can_access_applicants,
    change_application_status,
    create_job,
    job_card,
    list_applications,
    list_open_jobs,
)
from app.services.profiles import list_discoverable_profiles, public_profile_fields
from app.services.vacancies import collector_authorized
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(tags=["jobs"])


def _is_employer(user: User | None) -> bool:
    return user is not None and user.account_type == AccountType.EMPLOYER.value


def _form_context(db, user: User, *, values: dict[str, str], error: str | None = None):
    return {
        "title": "Post a job",
        "user": user,
        "values": values,
        "job_types": list(JOB_TYPE_LABELS.items()),
        "work_modes": list(WORK_MODE_LABELS.items()),
        "error": error,
        "organizations": approved_organizations(db, user),
    }


_EMPTY_FORM = {
    "title": "",
    "organization": "",
    "location": "",
    "job_type": "full_time",
    "work_mode": "on_site",
    "salary_min": "",
    "salary_max": "",
    "description": "",
    "country_code": "NG",
    "closing_date": "",
}


@router.get("/jobs")
def jobs_page(
    request: Request,
    job_type: str = Query("", alias="type"),
    q: str = Query("", max_length=120),
    country: str = Query("", max_length=2),
    scope: str = Query("", max_length=20),
    location: str = Query("", max_length=100),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    job_type = job_type if job_type in JOB_TYPE_LABELS else ""
    scope = "international" if scope == "international" else ""
    jobs = list_open_jobs(
        db,
        job_type=job_type or None,
        query=q,
        country_code=country,
        international_only=scope == "international",
        location=location,
    )
    return render(
        request,
        "jobs/index.html",
        {
            "title": "Job Opportunities",
            "user": user,
            "jobs": [job_card(job) for job in jobs],
            "job_types": list(JOB_TYPE_LABELS.items()),
            "job_type": job_type if job_type in JOB_TYPE_LABELS else "",
            "q": q,
            "country": country.upper(),
            "scope": scope,
            "location": location,
            "is_employer": _is_employer(user),
        },
    )


@router.get("/jobs/new")
def new_job_form(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    if not _is_employer(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only employer accounts can post jobs.",
        )
    return render(request, "jobs/new.html", _form_context(db, user, values=dict(_EMPTY_FORM)))


@router.post("/jobs")
def publish_job(
    request: Request,
    title: str = Form(""),
    organization: str = Form(""),
    location: str = Form(""),
    job_type: str = Form("full_time"),
    work_mode: str = Form("on_site"),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    description: str = Form(""),
    country_code: str = Form(""),
    closing_date: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    if not _is_employer(user):
        raise HTTPException(status_code=403, detail="Only employers can post jobs.")
    values = {
        "title": title,
        "organization": organization,
        "location": location,
        "job_type": job_type,
        "work_mode": work_mode,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "description": description,
        "country_code": country_code,
        "closing_date": closing_date,
    }
    try:
        create_job(
            db,
            user,
            title=title,
            organization=organization,
            location=location,
            job_type=job_type,
            work_mode=work_mode,
            salary_min=salary_min,
            salary_max=salary_max,
            description=description,
            country_code=country_code,
            closing_date=closing_date,
        )
    except JobError as exc:
        return render(
            request,
            "jobs/new.html",
            _form_context(db, user, values=values, error=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return redirect_feedback(
        request, "/jobs",
        message(
            'Job published',
            'Your listing is now available on the jobs page.',
        ),
    )


@router.get("/employers")
def employers_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    cards = [
        {"profile": profile, "fields": public_profile_fields(db, profile)}
        for profile in list_discoverable_profiles(db, limit=6)
    ]
    return render(
        request,
        "employer/index.html",
        {
            "title": "For employers",
            "user": user,
            "cards": cards,
            "is_employer": _is_employer(user),
        },
    )


def _job(db: Session, identifier: UUID, user: User | None) -> Job:
    job = retained_job(db, db.get(Job, identifier))
    if job and job.source_id:
        if collector_authorized(job.source) and job.status in {"open", "unconfirmed", "closed"}:
            return job
        raise HTTPException(status_code=404, detail="This opportunity is no longer available.")
    if job and not authorized(db, job.employer_user_id, job.employer_organization_id):
        raise HTTPException(status_code=404, detail="This job is no longer available.")
    if job is None or (
        job.status != JobStatus.OPEN
        and (
            user is None
            or (
                user.id != job.employer_user_id
                and db.get(SavedOpportunity, (user.id, job.id)) is None
            )
        )
    ):
        raise HTTPException(status_code=404, detail="This job is no longer available.")
    return job


def _detail(
    request: Request,
    db: Session,
    user: User | None,
    job: Job,
    *,
    error: str | None = None,
    cover_note: str = "",
) -> Response:
    return render(
        request,
        "jobs/show.html",
        {
            "title": job.title,
            "user": user,
            "job": job_card(job),
            "is_employer": _is_employer(user),
            "is_owner": bool(user and can_access_applicants(db, user, job)),
            "application": application_for_job(db, user, job) if user else None,
            "error": error,
            "cover_note": cover_note,
            "saved_opportunity": db.get(SavedOpportunity, (user.id, job.id)) if user else None,
        },
        status_code=400 if error else 200,
    )


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: UUID,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _job(db, job_id, user)
    if job.id != job_id:
        return RedirectResponse(f"/jobs/{job.id}", status_code=307)
    return _detail(request, db, user, job)


@router.post("/jobs/{job_id}/apply")
def apply(
    job_id: UUID,
    request: Request,
    cover_note: str = Form(""),
    consent: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    job = _job(db, job_id, user)
    if user.account_type != AccountType.NURSE.value:
        raise HTTPException(status_code=403, detail="Only nurses can apply for jobs.")
    try:
        if consent != "on":
            raise JobError("Agree to share your contact details with the employer to apply.")
        apply_for_job(db, user, job, cover_note=cover_note)
    except JobError as exc:
        return _detail(request, db, user, job, error=str(exc), cover_note=cover_note)
    return redirect_feedback(
        request, "/applications",
        message(
            'Application sent',
            'Track your application and its status here.',
        ),
    )


@router.get("/applications")
def applications(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    return render(
        request,
        "jobs/applications.html",
        {
            "title": "Applications",
            "user": user,
            "is_employer": _is_employer(user),
            "applications": list_applications(db, user),
            "status_labels": APPLICATION_STATUS_LABELS,
        },
    )


@router.post("/applications/{application_id}/status")
def application_status(
    request: Request,
    application_id: UUID,
    new_status: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    application = db.get(JobApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404)
    is_owner = can_access_applicants(db, user, application.job)
    is_applicant = application.applicant_user_id == user.id
    if not (is_owner or is_applicant):
        raise HTTPException(status_code=404)
    try:
        change_application_status(db, user, application, new_status)
    except JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return redirect_feedback(
        request, f"/applications/{application.id}",
        message(
            'Application updated',
            'The new application status has been saved.',
        ),
    )


@router.get("/applications/{application_id}")
def application_detail(
    application_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    application = db.get(JobApplication, application_id)
    if application is None or not (
        user.id == application.applicant_user_id
        or can_access_applicants(db, user, application.job)
    ):
        raise HTTPException(status_code=404)
    return render(
        request,
        "jobs/applications.html",
        {
            "title": "Application",
            "user": user,
            "is_employer": application.job.employer_user_id == user.id,
            "applications": [application],
            "status_labels": APPLICATION_STATUS_LABELS,
        },
    )
