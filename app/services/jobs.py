"""Job listings: posting by employer accounts and public reads."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jobs import Job, JobStatus, JobType, WorkMode
from app.models.user import AccountType, User

TITLE_MAX = 120
ORGANIZATION_MAX = 160
LOCATION_MAX = 120
DESCRIPTION_MAX = 5000

JOB_TYPE_LABELS = {
    JobType.FULL_TIME.value: "Full-time",
    JobType.PART_TIME.value: "Part-time",
    JobType.CONTRACT.value: "Contract",
    JobType.INTERNSHIP.value: "Internship",
}
WORK_MODE_LABELS = {
    WorkMode.ON_SITE.value: "On-site",
    WorkMode.REMOTE.value: "Remote",
    WorkMode.FIELD.value: "Field",
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
    if not cleaned.isdigit():
        raise JobError(f"{field} must be a whole number of naira.")
    return int(cleaned)


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
) -> Job:
    if user.account_type != AccountType.EMPLOYER.value:
        raise JobError("Only employer accounts can post jobs.")
    if job_type not in JOB_TYPE_LABELS:
        raise JobError("Choose a valid job type.")
    if work_mode not in WORK_MODE_LABELS:
        raise JobError("Choose a valid work mode.")

    low = _naira(salary_min, "Minimum salary")
    high = _naira(salary_max, "Maximum salary")
    if low is not None and high is not None and low > high:
        raise JobError("Minimum salary cannot be higher than maximum salary.")

    job = Job(
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
        status=JobStatus.OPEN,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_open_jobs(
    db: Session, *, job_type: str | None = None, limit: int = 50
) -> list[Job]:
    statement = select(Job).where(Job.status == JobStatus.OPEN)
    if job_type:
        statement = statement.where(Job.job_type == job_type)
    return list(
        db.scalars(
            statement.order_by(Job.posted_at.desc(), Job.id.desc()).limit(limit)
        ).all()
    )


def salary_label(job: Job) -> str:
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