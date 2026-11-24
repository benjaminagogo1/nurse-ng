"""Repeatable aggregate coverage measurement using the public eligibility predicate.

Counts reuse the public-job eligibility predicate. Candidate sources and
held records must not be reported as available jobs; measurement is not a
live end-to-end check of an external application process.
"""

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models.jobs import Job
from app.models.recruitment import RecruitmentSource
from app.models.vacancies import VacancyRecord
from app.services.jobs import open_job_condition
from app.services.vacancies import collector_authorized


def measure_coverage(db):
    sources = list(db.scalars(select(RecruitmentSource)))
    pending = list(db.scalars(select(VacancyRecord).where(VacancyRecord.state == 'pending')))
    jobs = list(db.scalars(select(Job).where(open_job_condition())))
    return {
        'measured_at_utc': datetime.now(UTC).isoformat(),
        'eligibility_method': 'Full application open_job_condition(), including employer approval',
        'sources_by_approval': dict(Counter(source.verification_status for source in sources)),
        'approved_sources_by_health': dict(Counter(
            source.health_status for source in sources if source.verification_status == 'approved'
        )),
        'collector_authorized_sources': sum(collector_authorized(source) for source in sources),
        'vacancies_by_state': dict(db.execute(select(VacancyRecord.state, func.count())
                                             .group_by(VacancyRecord.state)).all()),
        'publicly_eligible_jobs': len(jobs),
        'public_jobs': [{'title': job.title, 'organization': job.organization,
                         'country': job.country_code} for job in jobs],
        'pending_issue_counts': dict(Counter(
            category for record in pending
            for category in {issue.split(':', 1)[0] for issue in record.issues}
        )),
        'pending_without_stored_issues': sum(not record.issues for record in pending),
    }
