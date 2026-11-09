"""Source registry with staff decisions and separately evaluated automatic activation."""

import hashlib
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.recruitment import (
    DiscoverySchedule,
    DiscoveryTask,
    RecruitmentOrganization,
    RecruitmentSource,
    SourceEvent,
)
from app.models.user import User, UserStatus
from app.services.recruitment_fetch import FetchError, public_url, url_key
from app.services.vacancy_extraction import in_scope

CATEGORIES = {
    "ministry": "Ministry of health",
    "health_commission": "Health service commission",
    "teaching_hospital": "Teaching hospital",
    "federal_medical_centre": "Federal Medical Centre",
    "specialist_hospital": "Specialist hospital",
    "private_hospital": "Private hospital",
    "healthcare": "Healthcare organisation",
    "recruitment_agency": "Recruitment agency",
    "government_portal": "Government recruitment portal",
    "youth_programme": "Youth fellowship or graduate programme",
    "digital_health": "Digital health organisation",
    "primary_healthcare": "Primary healthcare agency",
    "public_health": "Public health agency",
    "unconfirmed": "Organisation type not confirmed",
}
METHODS = {
    "unconfirmed": "Not established",
    "api": "Official API",
    "rss": "RSS feed",
    "html": "Permitted website collection",
    "manual": "Administrator-assisted",
}
CHECKS = {
    "identity": "Organisation identity",
    "domain": "Website association",
    "authority": "Recruitment authority",
    "licensing": "Applicable registration and licensing",
    "permission": "Collection and republication permission",
}
REUSE_BASES = {
    "legal_basis": "Documented legal basis, including applicable government-publication rules",
    "published_licence": "Published licence or reuse terms",
    "written_authorization": "Written authorization from the rights holder",
}
REUSE_RIGHTS = {
    "allow_collection": "Collect using the selected method",
    "allow_snapshot_retention": "Retain complete original page snapshots and extracted records",
    "allow_republication": "Publish normalized vacancy content on Nurse.ng with attribution",
}


class RecruitmentError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def require_operator(db: Session, actor: User) -> None:
    valid = db.scalar(
        select(User.id).where(
            User.id == actor.id,
            User.is_staff.is_(True),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    )
    if valid is None:
        raise RecruitmentError("An active staff account is required.")


def clean(value: str, label: str, maximum: int, *, required: bool = True) -> str:
    result = (value or "").strip()
    if (required and not result) or len(result) > maximum:
        raise RecruitmentError(
            f"{label} is required and must be at most {maximum} characters."
            if required
            else f"{label} must be at most {maximum} characters."
        )
    return result


def country(value: str) -> str:
    result = (value or "").strip().upper()
    if result and not re.fullmatch(r"[A-Z]{2}", result):
        raise RecruitmentError("Use a two-letter country code, or leave it blank if unknown.")
    return result


def checked_url(value: str) -> str:
    try:
        return public_url((value or "").strip())
    except FetchError as exc:
        raise RecruitmentError(str(exc)) from None


def event(
    db: Session,
    source: RecruitmentSource,
    kind: str,
    *,
    actor: User | None = None,
    reference: str = "",
    details: dict | None = None,
    task_id=None,
) -> None:
    db.add(
        SourceEvent(
            source_id=source.id,
            actor_id=actor.id if actor else None,
            task_id=task_id,
            kind=kind,
            reference_url=reference[:2048],
            details=details or {},
            created_at=now(),
        )
    )


def register_candidate(
    db: Session,
    *,
    identity_key: str,
    name: str,
    category: str,
    country_code: str,
    location: str,
    website_url: str,
    source_url: str,
    discovered_via: str,
    reference: str,
    source_type: str = "institution_site",
    actor: User | None = None,
    task_id=None,
    evidence: dict | None = None,
    organization: RecruitmentOrganization | None = None,
) -> tuple[RecruitmentSource, bool]:
    """Write pending candidates only, in the caller's transaction."""
    source_url = checked_url(source_url)
    key = url_key(source_url)
    if discovered_via == "search":
        known = db.scalar(select(RecruitmentSource).where(RecruitmentSource.url_key == key))
        if known is not None:
            # Search must not duplicate stronger identity evidence or bypass a prior rejection.
            return known, False
    if organization is None:
        organization = db.scalar(
            select(RecruitmentOrganization).where(
                RecruitmentOrganization.identity_key == identity_key,
            )
        )
    if organization is None:
        organization = RecruitmentOrganization(
            identity_key=clean(identity_key, "Identity reference", 160),
            name=clean(name, "Organisation name", 250),
            category=category,
            country_code=country(country_code),
            location=location[:250],
            website_url=checked_url(website_url) if website_url else "",
        )
        db.add(organization)
        db.flush()
    source = db.scalar(
        select(RecruitmentSource).where(
            RecruitmentSource.organization_id == organization.id,
            RecruitmentSource.url_key == key,
        )
    )
    if source is not None:
        # In particular, do not reset a rejected/revoked source or replace its exact URL.
        return source, False
    source = RecruitmentSource(
        organization_id=organization.id,
        original_url=source_url,
        url_key=key,
        discovered_via=discovered_via,
        source_type=source_type,
        next_check_at=now(),
    )
    db.add(source)
    db.flush()
    event(
        db,
        source,
        "discovered",
        actor=actor,
        reference=reference,
        task_id=task_id,
        details={
            "method": discovered_via,
            "evidence": evidence or {},
            "notice": "Discovery information is not verification.",
        },
    )
    return source, True


def register_manual_source(
    db: Session,
    actor: User,
    *,
    name: str,
    category: str,
    country_code: str,
    location: str,
    website_url: str,
    source_url: str,
) -> RecruitmentSource:
    require_operator(db, actor)
    name = clean(name, "Organisation name", 250)
    if category not in CATEGORIES:
        raise RecruitmentError("Choose an organisation category.")
    code = country(country_code)
    site = checked_url(website_url)
    identity = hashlib.sha256(f"{name.casefold()}|{code}|{url_key(site)}".encode()).hexdigest()
    source, _ = register_candidate(
        db,
        identity_key=f"manual:{identity}",
        name=name,
        category=category,
        country_code=code,
        location=clean(location, "Location", 250, required=False),
        website_url=site,
        source_url=source_url,
        discovered_via="manual",
        reference=site,
        source_type="recruitment_page",
        actor=actor,
    )
    db.commit()
    return source


def approval_current(source: RecruitmentSource, *, at: datetime | None = None) -> bool:
    return bool(
        source.verification_status == "approved"
        and source.approval_expires_at
        and utc(source.approval_expires_at) > (at or now())
    )


def collection_authorized(source: RecruitmentSource, *, at: datetime | None = None) -> bool:
    """Shared gate for subsequent vacancy adapters; page discovery does not use this permission."""
    from app.services.factual_opportunities import index_authorized

    return bool(
        approval_current(source, at=at)
        and (
            (source.permission_status == "permitted" and reuse_authorized(source))
            or index_authorized(source)
        )
        and source.collection_method in {"api", "rss", "html"}
        and source.automation_status == "monitoring"
    )


def reuse_authorized(source: RecruitmentSource) -> bool:
    """Recorded reuse evidence, never an inference from public access or robots.txt."""
    return bool(
        source.reuse_basis in REUSE_BASES
        and all(getattr(source, right) for right in REUSE_RIGHTS)
        and source.reuse_url_prefix
        and in_scope(source.original_url, source.reuse_url_prefix)
        and (not source.observed_url or in_scope(source.observed_url, source.reuse_url_prefix))
    )


def review_source(
    db: Session,
    actor: User,
    source: RecruitmentSource,
    *,
    revision: int,
    action: str,
    note: str,
    checks: dict[str, dict] | None = None,
    method: str = "unconfirmed",
    expires_at: datetime | None = None,
    licensing_applicability: str = "required",
    reuse: dict | None = None,
) -> None:
    require_operator(db, actor)
    note = clean(note, "Decision note", 3000)
    values: dict = {"revision": revision + 1}
    details: dict = {"note": note, "previous_status": source.verification_status}
    if action == "approve":
        if not source.organization.country_code or source.organization.category == "unconfirmed":
            raise RecruitmentError(
                "Confirm the organisation's country and category before approval."
            )
        if method not in METHODS or method == "unconfirmed":
            raise RecruitmentError("Select the permitted collection method.")
        if not expires_at or not now() < utc(expires_at) <= now() + timedelta(days=366):
            raise RecruitmentError("Choose a future review expiry within the next year.")
        if licensing_applicability not in {"required", "not_applicable"}:
            raise RecruitmentError("Record whether licensing applies in this jurisdiction.")
        recorded = {}
        for key, label in CHECKS.items():
            item = (checks or {}).get(key, {})
            recorded[key] = {
                "note": clean(item.get("note", ""), f"{label} evidence", 2000),
                "url": checked_url(item.get("url", "")),
            }
        reuse = reuse or {}
        if reuse.get("basis") not in REUSE_BASES:
            raise RecruitmentError(
                "Record the applicable legal basis, published terms or written authorization "
                "for reuse."
            )
        scope = checked_url(reuse.get("url_prefix", ""))
        if not in_scope(source.original_url, scope) or (
            source.observed_url and not in_scope(source.observed_url, scope)
        ):
            raise RecruitmentError(
                "The permission URL scope must cover the original and observed source."
            )
        for right, label in REUSE_RIGHTS.items():
            if reuse.get(right) is not True:
                raise RecruitmentError(f"Permission evidence must explicitly allow: {label}.")
        values.update(
            approval_mode="staff",
            verification_status="approved",
            permission_status="permitted",
            collection_method=method,
            access_notes=recorded["permission"]["note"],
            last_verified_at=now(),
            approval_expires_at=utc(expires_at),
            automation_status="manual" if method == "manual" else "monitoring",
            reuse_basis=reuse["basis"],
            reuse_url_prefix=scope,
            **{right: True for right in REUSE_RIGHTS},
            # A new grant must not silently reactivate an old collector configuration.
            collection_adapter="",
            vacancy_url_prefix="",
            deadline_timezone="",
        )
        details.update(
            checks=recorded,
            method=method,
            expires_at=utc(expires_at).isoformat(),
            licensing_applicability=licensing_applicability,
            reuse={
                "basis": reuse["basis"],
                "url_prefix": scope,
                **{right: True for right in REUSE_RIGHTS},
            },
            policy_version=2,
        )
    elif action in {"reject", "revoke"}:
        values.update(
            approval_mode="staff",
            verification_status="rejected" if action == "reject" else "revoked",
            permission_status="unknown",
            automation_status="paused",
            approval_expires_at=None,
        )
    elif action == "pause":
        values["automation_status"] = "paused"
    elif action == "resume":
        if source.verification_status in {"rejected", "revoked"}:
            raise RecruitmentError("Reopen the source for review before resuming checks.")
        values.update(automation_status="monitoring", next_check_at=now())
    elif action == "reopen":
        values.update(
            approval_mode="staff",
            verification_status="pending",
            permission_status="unknown",
            approval_expires_at=None,
            automation_status="monitoring",
            next_check_at=now(),
        )
    elif action == "automatic":
        if source.verification_status in {"rejected", "revoked"}:
            raise RecruitmentError("Reopen the source before requesting automatic assessment.")
        values.update(
            approval_mode="",
            activation_review={},
            verification_status="pending",
            permission_status="unknown",
            approval_expires_at=None,
            collection_adapter="",
            automation_status="monitoring",
            next_check_at=now(),
        )
    else:
        raise RecruitmentError("Choose a supported review action.")
    changed = db.execute(
        update(RecruitmentSource)
        .where(
            RecruitmentSource.id == source.id,
            RecruitmentSource.revision == revision,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise RecruitmentError(
            "This source changed while you were reviewing it. Reload and review again."
        )
    event(db, source, action, actor=actor, details=details)
    db.commit()
    db.refresh(source)


def update_organization(
    db: Session,
    actor: User,
    source: RecruitmentSource,
    *,
    revision: int,
    name: str,
    category: str,
    country_code: str,
    location: str,
) -> None:
    require_operator(db, actor)
    if category not in CATEGORIES:
        raise RecruitmentError("Choose an organisation category.")
    data = dict(
        name=clean(name, "Organisation name", 250),
        category=category,
        country_code=country(country_code),
        location=clean(location, "Location", 250, required=False),
    )
    changed = db.execute(
        update(RecruitmentSource)
        .where(
            RecruitmentSource.id == source.id,
            RecruitmentSource.revision == revision,
        )
        .values(revision=revision + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise RecruitmentError("This source changed. Reload before editing its organisation.")
    for key, value in data.items():
        setattr(source.organization, key, value)
    db.flush()
    related = list(
        db.scalars(
            select(RecruitmentSource)
            .where(
                RecruitmentSource.organization_id == source.organization_id,
            )
            .execution_options(populate_existing=True)
        )
    )
    for item in related:
        item.approval_mode = "staff"
        if item.verification_status == "approved":
            item.verification_status = "pending"
            item.permission_status = "unknown"
            item.approval_expires_at = None
        item.revision += 1
        event(db, item, "organisation_updated", actor=actor, details=data)
    db.commit()


def add_schedule(
    db: Session,
    actor: User,
    *,
    name: str,
    provider: str,
    country_code: str,
    query: str,
    interval_hours: int,
) -> DiscoverySchedule:
    require_operator(db, actor)
    return _add_schedule(
        db,
        name=name,
        provider=provider,
        country_code=country_code,
        query=query,
        interval_hours=interval_hours,
    )


def _add_schedule(
    db: Session, *, name: str, provider: str, country_code: str, query: str, interval_hours: int
) -> DiscoverySchedule:
    from app.core.config import settings

    if provider not in {"ror", "brave", "search"}:
        raise RecruitmentError("Choose a supported discovery provider.")
    from app.services.recruitment_search import search_available

    if provider == "search" and not search_available():
        raise RecruitmentError("Configure at least one SearXNG instance. Brave is optional.")
    if provider == "brave" and not (
        settings.recruitment_search_key and settings.recruitment_search_permission_reference
    ):
        raise RecruitmentError(
            "Search needs an API key and a permission reference for stored results."
        )
    if not 1 <= interval_hours <= 720:
        raise RecruitmentError("Discovery intervals must be between 1 and 720 hours.")
    name = clean(name, "Schedule name", 120)
    if db.scalar(select(DiscoverySchedule.id).where(DiscoverySchedule.name == name)):
        raise RecruitmentError("A discovery schedule already has that name.")
    query = clean(query, "Search query", 300, required=provider in {"brave", "search"})
    schedule = DiscoverySchedule(
        name=name,
        provider=provider,
        country_code=country(country_code),
        query=query,
        interval_hours=interval_hours,
        next_run_at=now(),
    )
    db.add(schedule)
    db.commit()
    return schedule


def list_sources(
    db: Session, *, query: str = "", status: str = "", country_code: str = "", page: int = 1
) -> tuple[list[RecruitmentSource], int]:
    statement = select(RecruitmentSource).join(RecruitmentOrganization)
    if status in {"pending", "approved", "rejected", "revoked"}:
        statement = statement.where(RecruitmentSource.verification_status == status)
    if country_code:
        statement = statement.where(RecruitmentOrganization.country_code == country_code.upper())
    if query:
        statement = statement.where(
            or_(
                RecruitmentOrganization.name.icontains(query, autoescape=True),
                RecruitmentSource.original_url.icontains(query, autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(
                case((RecruitmentOrganization.country_code == "NG", 0), else_=1),
                RecruitmentSource.created_at.desc(),
                RecruitmentSource.id.desc(),
            )
            .offset((max(1, page) - 1) * 25)
            .limit(25)
        )
    )
    return rows, total


def initialize_discovery(db: Session) -> dict[str, int]:
    """Set up Nigerian-first discovery; starter sites remain unapproved candidates."""
    schedules = ensure_search_schedule(db)
    for name, code, interval in [
        ("Nigerian healthcare institutions", "NG", 24),
        ("Worldwide healthcare institutions", "", 168),
    ]:
        existing = db.scalar(select(DiscoverySchedule).where(DiscoverySchedule.name == name))
        if not existing:
            _add_schedule(
                db, name=name, provider="ror", country_code=code, query="", interval_hours=interval
            )
            schedules += 1
        elif (
            code == ""
            and existing.provider == "ror"
            and existing.country_code == ""
            and existing.query == ""
            and existing.interval_hours == 24
        ):
            # Upgrade the original built-in default, retaining pause state and cursor.
            existing.interval_hours = interval
    _, created = register_candidate(
        db,
        identity_key="user-provided:lshsc",
        name="Lagos State Health Service Commission",
        category="health_commission",
        country_code="NG",
        location="Lagos",
        website_url="https://lshsc.ng",
        source_url="https://lshsc.ng/recruitment",
        discovered_via="manual",
        reference="https://lshsc.ng/recruitment",
        source_type="recruitment_page",
        evidence={"note": "Exact source supplied by the user; pending review."},
    )
    sources = int(created)
    for identity, name, category, website, url, reference in [
        (
            "ng-priority:health-ministry",
            "Federal Ministry of Health and Social Welfare",
            "ministry",
            "https://health.gov.ng/",
            "https://health.gov.ng/",
            "https://health.gov.ng/",
        ),
        (
            "ng-priority:health-fellows",
            "National Health Fellows Programme",
            "youth_programme",
            "https://healthfellows.ng/",
            "https://healthfellows.ng/",
            "https://health.gov.ng/",
        ),
        (
            "ng-priority:jubilee-fellows",
            "Nigeria Jubilee Fellows Programme",
            "youth_programme",
            "https://njfp.ng/",
            "https://njfp.ng/",
            "https://njfp.ng/",
        ),
        (
            "ng-priority:nphcda",
            "National Primary Health Care Development Agency",
            "primary_healthcare",
            "https://nphcda.gov.ng/",
            "https://nphcda.gov.ng/",
            "https://nphcda.gov.ng/",
        ),
        (
            "ng-priority:ncdc",
            "Nigeria Centre for Disease Control and Prevention",
            "public_health",
            "https://ncdc.gov.ng/",
            "https://ncdc.gov.ng/",
            "https://ncdc.gov.ng/",
        ),
        (
            "ng-priority:lagos-health",
            "Lagos State Ministry of Health",
            "ministry",
            "https://health.lagosstate.gov.ng/",
            "https://health.lagosstate.gov.ng/",
            "https://lagosstate.gov.ng/",
        ),
        (
            "ng-priority:lagoon",
            "Iwosan Lagoon Hospitals",
            "private_hospital",
            "https://www.lagoonhospitals.com/",
            "https://www.lagoonhospitals.com/careers/",
            "https://www.lagoonhospitals.com/",
        ),
    ]:
        # Do not duplicate a URL already registered under another identity or
        # override a staff decision. These are starting points, not a closed list.
        if db.scalar(select(RecruitmentSource.id).where(RecruitmentSource.url_key == url_key(url))):
            continue
        _, created = register_candidate(
            db,
            identity_key=identity,
            name=name,
            category=category,
            country_code="NG",
            location="",
            website_url=website,
            source_url=url,
            discovered_via="manual",
            reference=reference,
            source_type="recruitment_page" if "/careers/" in url else "institution_site",
            evidence={
                "note": "Nigerian opportunity discovery starting point. "
                "Not a current vacancy or approval; normal source checks still apply."
            },
        )
        sources += int(created)
    db.commit()
    return {"schedules": schedules, "sources": sources}


def ensure_search_schedule(db: Session) -> int:
    """A configured provider must actually have a queue schedule; preserve staff pauses."""
    from app.services.recruitment_search import search_available

    if not search_available():
        return 0
    name = "Nigerian opportunities across the web"
    if db.scalar(select(DiscoverySchedule.id).where(DiscoverySchedule.name == name)):
        return 0
    _add_schedule(
        db,
        name=name,
        provider="search",
        country_code="NG",
        query="{category} {region} {country} applications careers opportunities",
        interval_hours=6,
    )
    return 1


def request_inspection(db: Session, actor: User, source: RecruitmentSource) -> None:
    require_operator(db, actor)
    if source.automation_status != "monitoring" or source.verification_status in {
        "rejected",
        "revoked",
    }:
        raise RecruitmentError("Resume page monitoring before requesting a check.")
    source.next_check_at = now()
    event(db, source, "check_requested", actor=actor)
    db.commit()


def set_schedule_enabled(
    db: Session, actor: User, schedule: DiscoverySchedule, *, enabled: bool
) -> None:
    require_operator(db, actor)
    schedule.enabled = enabled
    if enabled:
        schedule.next_run_at = now()
    db.commit()


def task_counts(db: Session) -> dict[str, int]:
    return dict(
        db.execute(select(DiscoveryTask.status, func.count()).group_by(DiscoveryTask.status)).all()
    )
