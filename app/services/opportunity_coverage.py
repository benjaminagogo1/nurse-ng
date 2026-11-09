"""Operational Nigerian coverage, without treating discovered sites as active vacancies."""

import re

from sqlalchemy import func, select

from app.core.config import settings
from app.models.jobs import Job
from app.models.recruitment import DiscoveryTask, RecruitmentOrganization, RecruitmentSource
from app.services.jobs import JOB_TYPE_LABELS, open_job_condition
from app.services.recruitment import CATEGORIES, now, utc
from app.services.recruitment_discovery import NIGERIAN_REGIONS
from app.services.vacancies import FRESHNESS, collector_authorized


def coverage(db):
    sources = list(
        db.scalars(
            select(RecruitmentSource)
            .join(RecruitmentOrganization)
            .where(RecruitmentOrganization.country_code == "NG")
        )
    )
    regions = {name: 0 for name in NIGERIAN_REGIONS}
    categories = {
        key: {"label": label, "registered": 0, "collecting": 0} for key, label in CATEGORIES.items()
    }
    unmapped = 0
    for source in sources:
        category = categories.get(source.organization.category, categories["unconfirmed"])
        category["registered"] += 1
        category["collecting"] += bool(
            collector_authorized(source)
            and source.health_status == "healthy"
            and source.last_success_at
            and utc(source.last_success_at) >= now() - FRESHNESS
        )
        location = source.organization.location
        matched = []
        for region in regions:
            label = (
                "Abuja|Federal Capital Territory|FCT"
                if region.startswith("Federal Capital")
                else re.escape(region)
            )
            if re.search(r"\b(?:" + label + r")\b", location, re.I):
                matched.append(region)
        for region in matched:
            regions[region] += 1
        unmapped += not bool(matched)
    job_counts = dict(
        db.execute(
            select(Job.job_type, func.count(Job.id))
            .where(Job.country_code == "NG", open_job_condition())
            .group_by(Job.job_type)
        ).all()
    )
    midnight = now().replace(hour=0, minute=0, second=0, microsecond=0)
    attempts = (
        db.scalar(
            select(func.sum(DiscoveryTask.attempts)).where(DiscoveryTask.started_at >= midnight)
        )
        or 0
    )
    return {
        "daily_attempts": attempts,
        "daily_limit": settings.recruitment_daily_task_limit,
        "categories": list(categories.values()),
        "regions": regions,
        "unmapped": unmapped,
        "registered": len(sources),
        "collecting": sum(row["collecting"] for row in categories.values()),
        "opportunities": [
            {"label": JOB_TYPE_LABELS.get(key, "Type not stated"), "count": count}
            for key, count in job_counts.items()
        ],
        "current": sum(job_counts.values()),
    }
