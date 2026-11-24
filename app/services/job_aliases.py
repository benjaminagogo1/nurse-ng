"""Resolve a retired vacancy only to its recorded, matching announcement.

Aliases preserve saved links after duplicate consolidation. Matching stored
announcement identity is required; this resolver must not redirect one role
to an unrelated vacancy.
"""

from uuid import UUID

from app.models.jobs import Job
from app.services.vacancy_quality import canonical_vacancy_url


def retained_job(db, job):
    if job is None or not job.normalized_data.get("_duplicate_of_job"):
        return job
    if not job.source_id or job.status != "withdrawn":
        return None
    try:
        target = db.get(Job, UUID(job.normalized_data["_duplicate_of_job"]))
    except (ValueError, TypeError, AttributeError):
        return None
    original_url = job.normalized_data.get("announcement_url", "")
    if (not original_url or not target or not target.source_id
            or target.normalized_data.get("_duplicate_of_job")
            or canonical_vacancy_url(target.normalized_data.get("announcement_url", ""))
            != canonical_vacancy_url(original_url)):
        return None
    return target
