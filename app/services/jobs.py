"""Job listings: posting by employer accounts and public reads."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.jobs import Job, JobApplication, JobStatus, JobType, WorkMode
from app.models.recruitment import RecruitmentSource
from app.models.user import AccountType, User
from app.services.notifications import emit
from app.services.recruitment import REUSE_BASES, utc
from app.services.vacancies import FRESHNESS, collector_authorized

TITLE_MAX = 120
ORGANIZATION_MAX = 160
LOCATION_MAX = 120
DESCRIPTION_MAX = 5000

JOB_TYPE_LABELS = {
    JobType.FULL_TIME.value: "Full-time",
    JobType.PART_TIME.value: "Part-time",
    JobType.CONTRACT.value: "Contract",
    JobType.INTERNSHIP.value: "Internship",
    JobType.FELLOWSHIP.value: "Fellowship",
    JobType.GRADUATE_PROGRAMME.value: "Graduate programme",
}
WORK_MODE_LABELS = {
    WorkMode.ON_SITE.value: "On-site",
    WorkMode.REMOTE.value: "Remote",
    WorkMode.FIELD.value: "Field",
}
APPLICATION_STATUS_LABELS = {
    "submitted": "Submitted",
    "reviewing": "In review",
    "shortlisted": "Shortlisted",
    "rejected": "Not selected",
    "withdrawn": "Withdrawn",
}


class JobError(ValueError):
    """A job input the poster can correct."""


def _clean(value: str, *, field: str, maximum: int, required: bool = False) -> str:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise JobError(f"{field} is required.")
    if len(cleaned) > maximum:
        raise JobError(f"{field} must be at most {maximum} characters.")
    return cleaned


def _naira(value: str, field: str) -> int | None:
    cleaned = str(value or "").replace(",", "").strip()
    if not cleaned:
        return None
    if not cleaned.isascii() or not cleaned.isdigit() or len(cleaned) > 10:
        raise JobError(f"{field} must be a whole number of naira.")
    amount = int(cleaned)
    if amount > 2_000_000_000:
        raise JobError(f"{field} must be at most ₦2,000,000,000.")
    return amount


def create_job(
    db: Session,
    user: User,
    *,
    title: str,
    organization: str,
    location: str,
    job_type: str,
    work_mode: str,
    salary_min: str,
    salary_max: str,
    description: str,
    country_code: str = "",
    closing_date: str = "",
) -> Job:
    if user.account_type != AccountType.EMPLOYER.value:
        raise JobError("Only employer accounts can post jobs.")
    if job_type not in JOB_TYPE_LABELS:
        raise JobError("Choose a valid job type.")
    if work_mode not in WORK_MODE_LABELS:
        raise JobError("Choose a valid work mode.")
    code = country_code.strip().upper()
    if code and not re.fullmatch(r"[A-Z]{2}", code):
        raise JobError("Use a two-letter country code or leave it blank.")

    from app.services.vacancy_extraction import parse_date

    deadline_zone = "Africa/Lagos" if code == "NG" else "UTC"
    closes_at = (
        parse_date(closing_date.strip(), deadline_zone, closing=True) if closing_date else None
    )
    if closing_date and (
        not closes_at
        or closes_at <= datetime.now(UTC)
        or (code != "NG" and "T" not in closing_date)
    ):
        raise JobError(
            "Enter a future deadline: YYYY-MM-DD for Nigeria, "
            "or an ISO timestamp with timezone for other countries."
        )
    low = _naira(salary_min, "Minimum salary")
    high = _naira(salary_max, "Maximum salary")
    if low is not None and high is not None and low > high:
        raise JobError("Minimum salary cannot be higher than maximum salary.")

    job = Job(
        created_at=datetime.now(UTC),
        employer_user_id=user.id,
        title=_clean(title, field="Job title", maximum=TITLE_MAX, required=True),
        organization=_clean(
            organization, field="Organization", maximum=ORGANIZATION_MAX, required=True
        ),
        location=_clean(location, field="Location", maximum=LOCATION_MAX),
        job_type=job_type,
        work_mode=work_mode,
        salary_min=low,
        salary_max=high,
        description=_clean(description, field="Description", maximum=DESCRIPTION_MAX),
        country_code=code,
        closes_at=closes_at,
        normalized_data={"closing_date": closing_date.strip(), "deadline_timezone": deadline_zone},
        status=JobStatus.OPEN,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_open_jobs(
    db: Session,
    *,
    job_type: str | None = None,
    query: str = "",
    limit: int = 50,
    country_code: str = "",
    international_only: bool = False,
    location: str = "",
) -> list[Job]:
    statement = select(Job).where(open_job_condition())
    if international_only:
        statement = statement.where(Job.country_code.not_in(["NG", ""]))
    if country_code:
        statement = statement.where(Job.country_code == country_code.upper())
    if location:
        statement = statement.where(Job.location.icontains(location.strip(), autoescape=True))
    if job_type:
        statement = statement.where(Job.job_type == job_type)
    if query.strip():
        statement = statement.where(
            or_(
                Job.title.icontains(query.strip(), autoescape=True),
                Job.organization.icontains(query.strip(), autoescape=True),
                Job.location.icontains(query.strip(), autoescape=True),
            )
        )
    return list(
        db.scalars(
            statement.order_by(
                case((Job.country_code == "NG", 0), else_=1),
                Job.posted_at.desc(),
                Job.id.desc(),
            ).limit(limit)
        ).all()
    )


def open_job_condition():
    timestamp = datetime.now(UTC)
    return and_(
        Job.status == JobStatus.OPEN,
        or_(Job.closes_at.is_(None), Job.closes_at > timestamp),
        or_(
            Job.source_id.is_(None),
            and_(
                Job.confirmed_at >= timestamp - FRESHNESS,
                or_(
                    Job.closes_at > timestamp,
                    and_(
                        Job.closes_at.is_(None),
                        Job.normalized_data["_index"]["accepting_applications"]
                        .as_boolean()
                        .is_(True),
                    ),
                ),
                Job.source.has(
                    and_(
                        RecruitmentSource.verification_status == "approved",
                        RecruitmentSource.approval_expires_at > timestamp,
                        RecruitmentSource.reuse_url_prefix != "",
                        RecruitmentSource.allow_collection.is_(True),
                        or_(
                            and_(
                                RecruitmentSource.permission_status == "permitted",
                                RecruitmentSource.reuse_basis.in_(list(REUSE_BASES)),
                                RecruitmentSource.allow_snapshot_retention.is_(True),
                                RecruitmentSource.allow_republication.is_(True),
                                RecruitmentSource.collection_adapter.in_(
                                    ["jsonld", "announcements"]
                                ),
                            ),
                            and_(
                                RecruitmentSource.permission_status == "limited",
                                RecruitmentSource.reuse_basis == "factual_index",
                                RecruitmentSource.approval_mode == "automatic",
                                RecruitmentSource.collection_adapter == "factual_index",
                                RecruitmentSource.allow_snapshot_retention.is_(False),
                                RecruitmentSource.allow_republication.is_(False),
                                RecruitmentSource.activation_review["evidence"]["mode"].as_string()
                                == "factual_index",
                                RecruitmentSource.activation_review["evidence"]["scope"].as_string()
                                == RecruitmentSource.reuse_url_prefix,
                                RecruitmentSource.activation_review["evidence"][
                                    "recruitment_page"
                                ].as_string()
                                == RecruitmentSource.observed_url,
                                RecruitmentSource.activation_review["evidence"][
                                    "requested_url"
                                ].as_string()
                                == RecruitmentSource.original_url,
                            ),
                        ),
                        RecruitmentSource.automation_status == "monitoring",
                        RecruitmentSource.collection_method == "html",
                        RecruitmentSource.health_status == "healthy",
                    )
                ),
            ),
        ),
    )


def effective_job_status(job: Job) -> str:
    timestamp = datetime.now(UTC)
    if not job.source_id:
        if job.closes_at and utc(job.closes_at) <= timestamp:
            return "closed"
        return job.status
    if job.closes_at and utc(job.closes_at) <= timestamp:
        return "closed"
    if (
        job.status != "open"
        or not collector_authorized(job.source)
        or job.source.health_status != "healthy"
        or not job.confirmed_at
        or utc(job.confirmed_at) < timestamp - FRESHNESS
    ):
        return "unconfirmed"
    if job.opens_at and utc(job.opens_at) > timestamp:
        return "upcoming"
    if job.closes_at and utc(job.closes_at) <= timestamp + timedelta(days=7):
        return "closing_soon"
    return "open"


def salary_label(job: Job) -> str:
    if job.source_id:
        data = job.normalized_data.get("salary", {})
        if not data:
            return "Salary not stated"

        def number(key):
            return f"{Decimal(data[key]):,}"

        if "value" in data:
            amount = number("value")
        elif "minValue" in data and "maxValue" in data:
            amount = f"{number('minValue')} – {number('maxValue')}"
        elif "minValue" in data:
            amount = "from " + number("minValue")
        else:
            amount = "up to " + number("maxValue")
        return f"{data['currency']} {amount}/{data['unit'].lower()}"
    low, high = job.salary_min, job.salary_max
    if low is None and high is None:
        return "Salary not stated"
    if low is not None and high is not None:
        return f"₦{low:,} - ₦{high:,}/month"
    if low is not None:
        return f"From ₦{low:,}/month"
    return f"Up to ₦{high:,}/month"


def posted_label(job: Job) -> str:
    posted = job.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - posted).days
    if days <= 0:
        return "Today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def job_card(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "title": job.title,
        "organization": job.organization,
        "location": job.location,
        "salary": salary_label(job),
        "type": JOB_TYPE_LABELS.get(job.job_type, job.job_type or "Employment type not stated"),
        "mode": WORK_MODE_LABELS.get(job.work_mode, job.work_mode or "Work mode not stated"),
        "posted": posted_label(job),
        "date_label": "First listed"
        if job.normalized_data.get("_index") and not job.normalized_data.get("publication_date")
        else "Posted",
        "factual_index": bool(job.normalized_data.get("_index")),
        "description": job.description,
        "external": bool(job.source_id),
        "country": job.country_code,
        "status": effective_job_status(job),
        "source_name": job.source.organization.name if job.source_id else "",
        "source_url": job.source.original_url if job.source_id else "",
        "announcement_url": job.normalized_data.get("announcement_url", "")
        if job.source_id
        else "",
        "closing_date": job.normalized_data.get("closing_date", ""),
        "deadline_timezone": job.normalized_data.get("_index", {}).get(
            "deadline_timezone", job.source.deadline_timezone
        )
        if job.source_id
        else job.normalized_data.get("deadline_timezone", ""),
        "confirmed_at": job.confirmed_at,
        "clarified": bool(job.normalized_data.get("_review")) if job.source_id else False,
        "licence": job.normalized_data.get("_licence") if job.source_id else None,
        "requirements": {
            label: job.normalized_data[key]
            for key, label in {
                "employment_type_text": "Employment terms stated by the source",
                "responsibilities": "Responsibilities",
                "qualifications": "Qualifications",
                "experience": "Experience",
                "registration_requirements": "Registration requirements",
                "skills": "Skills",
                "benefits": "Benefits",
            }.items()
            if job.source_id and job.normalized_data.get(key)
        },
    }


def application_for_job(db: Session, user: User, job: Job) -> JobApplication | None:
    return db.scalar(
        select(JobApplication).where(
            JobApplication.job_id == job.id, JobApplication.applicant_user_id == user.id
        )
    )


def apply_for_job(db: Session, user: User, job: Job, *, cover_note: str) -> JobApplication:
    if job.source_id:
        raise JobError("Follow the original announcement for this vacancy's application process.")
    if user.account_type != AccountType.NURSE.value:
        raise JobError("Applications are available to nurse accounts.")
    if job.status != JobStatus.OPEN or (job.closes_at and utc(job.closes_at) <= datetime.now(UTC)):
        raise JobError("This job is no longer accepting applications.")
    if not user.full_name:
        raise JobError("Add your full name in account settings before applying.")
    if application_for_job(db, user, job):
        raise JobError("You have already applied for this role.")
    application = JobApplication(
        job_id=job.id,
        applicant_user_id=user.id,
        candidate_name=user.full_name,
        candidate_phone=user.phone,
        candidate_email=user.email or "",
        cover_note=_clean(cover_note, field="Your note", maximum=3000),
        status="submitted",
    )
    db.add(application)
    try:
        db.flush()
        emit(
            db,
            actor_id=user.id,
            recipients={job.employer_user_id},
            category="applications",
            kind="application_received",
            event_key=f"application:{application.id}:submitted",
            application_id=application.id,
            application_status="submitted",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise JobError("You have already applied for this role.") from None
    db.refresh(application)
    return application


def list_applications(db: Session, user: User) -> list[JobApplication]:
    statement = select(JobApplication).options(joinedload(JobApplication.job))
    if user.account_type == AccountType.EMPLOYER.value:
        statement = statement.join(Job).where(Job.employer_user_id == user.id)
    else:
        statement = statement.where(JobApplication.applicant_user_id == user.id)
    return list(db.scalars(statement.order_by(JobApplication.created_at.desc()).limit(100)))


def change_application_status(
    db: Session, user: User, application: JobApplication, new_status: str
) -> None:
    owner = application.job.employer_user_id == user.id
    applicant = application.applicant_user_id == user.id
    if not (owner or applicant):
        raise JobError("This application is not available.")
    allowed = {"reviewing", "shortlisted", "rejected"} if owner else {"withdrawn"}
    previous = application.status
    if new_status not in allowed or previous == "withdrawn":
        raise JobError("This status change is not available.")
    if new_status == previous:
        return
    changed = db.execute(
        update(JobApplication)
        .where(
            JobApplication.id == application.id,
            JobApplication.status == previous,
        )
        .values(status=new_status)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise JobError("This application has changed. Reload it before updating its status.")
    recipient = application.applicant_user_id if owner else application.job.employer_user_id
    emit(
        db,
        actor_id=user.id,
        recipients={recipient},
        category="applications",
        kind="application_status",
        event_key=f"application:{application.id}:{uuid.uuid4().hex}",
        application_id=application.id,
        application_status=new_status,
    )
    db.commit()
