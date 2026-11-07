"""Approved-source vacancy ingestion and explicit exception review, in one transaction."""

import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.jobs import Job
from app.models.recruitment import RecruitmentSource
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.services.recruitment import (
    RecruitmentError,
    checked_url,
    clean,
    collection_authorized,
    event,
    now,
    require_operator,
    reuse_authorized,
    utc,
)
from app.services.recruitment_fetch import MAX_BYTES, FetchError
from app.services.vacancy_extraction import (
    extract_records,
    in_scope,
    normalize,
    parse_date,
    validation_issues,
)

FRESHNESS = timedelta(hours=48)
EDITABLE = {
    "title",
    "employer",
    "description",
    "country",
    "region",
    "city",
    "announcement_url",
    "closing_date",
    "publication_date",
    "opening_date",
}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def data_hash(value) -> str:
    return digest({key: data for key, data in value.items() if not key.startswith("_")})


def collector_authorized(source) -> bool:
    return bool(
        source
        and collection_authorized(source)
        and source.collection_method == "html"
        and source.collection_adapter == "jsonld"
        and source.vacancy_url_prefix
        and source.deadline_timezone
        and in_scope(source.vacancy_url_prefix, source.reuse_url_prefix)
    )


def activation_blockers(source) -> list[str]:
    """Explain authorization/configuration separately from reachability and vacancy count."""
    from app.services.recruitment import approval_current

    blockers = []
    if not approval_current(source):
        blockers.append(
            "A current source approval with identity and authority evidence is required."
        )
    if source.permission_status != "permitted" or not reuse_authorized(source):
        blockers.append(
            "Verified reuse evidence must cover collection, original snapshot retention "
            "and republication within the approved URL scope."
        )
    if source.automation_status != "monitoring":
        blockers.append("Automatic collection is paused or set to administrator-assisted mode.")
    if source.collection_method != "html":
        blockers.append("The available collector requires approval for website collection.")
    if source.collection_adapter != "jsonld" or not source.deadline_timezone:
        blockers.append(
            "Configure the structured JobPosting collector and deadline timezone after approval."
        )
    if not source.vacancy_url_prefix or not in_scope(
        source.vacancy_url_prefix, source.reuse_url_prefix
    ):
        blockers.append("The collector URL scope must be within the recorded permission scope.")
    return blockers


def configure_collector(
    db, actor, source, *, revision, enabled, url_prefix, timezone, note, reference
):
    require_operator(db, actor)
    note = clean(note, "Configuration reason and permission scope", 3000)
    reference = checked_url(reference)
    if enabled:
        if not collection_authorized(source) or source.collection_method != "html":
            raise RecruitmentError("Approve this source for permitted website collection first.")
        url_prefix = checked_url(url_prefix)
        if (
            urlsplit(url_prefix).query
            or urlsplit(url_prefix).fragment
            or not in_scope(source.original_url, url_prefix)
        ):
            raise RecruitmentError(
                "The vacancy URL scope must include this source, without query or fragment."
            )
        if not in_scope(url_prefix, source.reuse_url_prefix):
            raise RecruitmentError(
                "The collector URL scope cannot exceed the approved permission scope."
            )
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise RecruitmentError("Choose a valid IANA timezone, such as Africa/Lagos.") from None
    changed = db.execute(
        update(RecruitmentSource)
        .where(
            RecruitmentSource.id == source.id,
            RecruitmentSource.revision == revision,
        )
        .values(
            collection_adapter="jsonld" if enabled else "",
            vacancy_url_prefix=url_prefix if enabled else "",
            deadline_timezone=timezone if enabled else "",
            revision=revision + 1,
            next_check_at=now(),
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise RecruitmentError("This source changed. Reload before configuring collection.")
    mark_source_unconfirmed(db, source.id)
    event(
        db,
        source,
        "collector_configured",
        actor=actor,
        reference=reference,
        details={"enabled": enabled, "url_prefix": url_prefix, "timezone": timezone, "note": note},
    )
    db.commit()
    db.refresh(source)


def record_event(db, record, action, *, actor=None, note="", reference="", details=None):
    db.add(
        VacancyEvent(
            record_id=record.id,
            snapshot_id=record.snapshot_id,
            actor_id=actor.id if actor else None,
            action=action,
            created_at=now(),
            details={
                "note": note,
                "reference": reference,
                "normalized": record.normalized,
                "raw_record": record.raw_record,
                "issues": record.issues,
                **(details or {}),
            },
        )
    )


def mark_source_unconfirmed(db, source_id):
    db.execute(
        update(Job)
        .where(Job.source_id == source_id, Job.status == "open")
        .values(status="unconfirmed")
        .execution_options(synchronize_session=False)
    )


def _record_key(raw):
    identifier = raw.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    if isinstance(identifier, (str, int)) and str(identifier).strip():
        return digest({"identifier": str(identifier)})
    url = raw.get("url")
    if isinstance(url, str) and url:
        return digest({"url": url})
    return digest(raw)


def _publish(db, record, timestamp):
    """Exact announcement URLs deduplicate; conflicting records need a human decision."""
    from app.services.recruitment_fetch import url_key

    data, source = record.normalized, record.source
    key = url_key(data["announcement_url"])
    job = db.scalar(select(Job).where(Job.external_key == key).with_for_update(of=Job))
    if job:
        competitors = list(
            db.scalars(
                select(VacancyRecord).where(
                    VacancyRecord.job_id == job.id,
                    VacancyRecord.id != record.id,
                    VacancyRecord.state != "rejected",
                )
            )
        )
        if any(data_hash(other.normalized) != data_hash(data) for other in competitors):
            record.job_id = job.id
            record.issues = [
                *record.issues,
                "conflict: another source record disagrees about this vacancy",
            ]
            record.state = "pending"
            job.status = "unconfirmed"
            return
    else:
        job = Job(external_key=key, employer_user_id=None)
        db.add(job)
    # Retire the former public URL if this source changes the announcement identity.
    if record.job_id and record.job_id != job.id:
        old = db.get(Job, record.job_id)
        if old and old.source_id == record.source_id:
            old.status = "unconfirmed"
    job.source_id = source.id
    job.source = source
    job.title, job.organization, job.description = (
        data["title"],
        data["employer"],
        data["description"],
    )
    job.location = ", ".join(filter(None, [data.get("city"), data.get("region"), data["country"]]))[
        :250
    ]
    job.country_code = data["country"]
    job.job_type, job.work_mode = data.get("job_type", ""), data.get("work_mode", "")
    job.salary_min = job.salary_max = None
    job.normalized_data = data
    job.closes_at = parse_date(data["closing_date"], source.deadline_timezone, closing=True)
    job.opens_at = parse_date(data.get("opening_date", ""), source.deadline_timezone)
    job.posted_at = parse_date(data["publication_date"], source.deadline_timezone)
    job.confirmed_at = timestamp
    job.status = "open"
    db.flush()
    record.job_id, record.state = job.id, "published"


def ingest_page(db: Session, source, result: dict, timestamp):
    """Caller holds source/task locks and commits all observations together."""
    if not collector_authorized(source):
        raise RecruitmentError("Source permission changed before vacancy ingestion.")
    if not in_scope(result["observed_url"], source.reuse_url_prefix):
        raise RecruitmentError("The returned page is outside the approved reuse scope.")
    body = base64.b64decode(result["body_base64"], validate=True)
    if len(body) > MAX_BYTES or hashlib.sha256(body).hexdigest() != result["content_hash"]:
        raise RecruitmentError("The original source response could not be verified.")
    snapshot = db.scalar(
        select(VacancySnapshot).where(
            VacancySnapshot.source_id == source.id,
            VacancySnapshot.content_hash == result["content_hash"],
        )
    )
    if snapshot is None:
        snapshot = VacancySnapshot(
            source_id=source.id,
            original_url=source.original_url,
            observed_url=checked_url(result["observed_url"]),
            body=body,
            content_hash=result["content_hash"],
            collected_at=timestamp,
        )
        db.add(snapshot)
        db.flush()
    try:
        rows = extract_records(body)
    except FetchError as exc:
        source.health_status = "extraction_error"
        source.failure_count += 1
        mark_source_unconfirmed(db, source.id)
        event(
            db,
            source,
            "vacancy_extraction_failed",
            details={
                "snapshot_id": str(snapshot.id),
                "message": str(exc),
            },
        )
        return {"records": 0, "published": 0, "pending": 0, "error": str(exc)}
    keys = [_record_key(raw) for raw in rows]
    duplicated = {key for key in keys if keys.count(key) > 1}
    seen, published, pending = set(), 0, 0
    for raw, key in zip(rows, keys, strict=True):
        if key in seen:
            continue
        seen.add(key)
        record = db.scalar(
            select(VacancyRecord).where(
                VacancyRecord.source_id == source.id, VacancyRecord.record_key == key
            )
        )
        raw_hash = digest(raw)
        previous_state = record.state if record else None
        changed = record is None or record.content_hash != raw_hash
        if record is None:
            record = VacancyRecord(
                source_id=source.id,
                source=source,
                record_key=key,
                first_seen_at=timestamp,
                snapshot_id=snapshot.id,
            )
            db.add(record)
        record.snapshot_id, record.last_seen_at = snapshot.id, timestamp
        if changed:
            record.raw_record, record.content_hash, record.normalized = (
                raw,
                raw_hash,
                normalize(raw),
            )
        data = record.normalized
        review = data.get("_review", {})
        record.issues = validation_issues(
            data,
            source,
            employer_confirmed=review.get("employer_confirmed", False),
            nursing_confirmed=review.get("nursing_confirmed", False),
        )
        if key in duplicated:
            record.issues = [
                *record.issues,
                "identifier: conflicting or repeated records share an identifier",
            ]
        record.state = "rejected" if previous_state == "rejected" else "pending"
        record.revision = (record.revision or 0) + 1
        db.flush()
        if record.state != "rejected" and not record.issues:
            _publish(db, record, timestamp)
        elif record.job_id:
            job = db.get(Job, record.job_id)
            if job and job.source_id == source.id:
                job.status = "unconfirmed"
        if changed or record.state != previous_state:
            record_event(db, record, "collected", details={"state": record.state})
        published += record.state == "published"
        pending += record.state == "pending"
        db.flush()
    for record in db.scalars(select(VacancyRecord).where(VacancyRecord.source_id == source.id)):
        if record.record_key not in seen and record.state not in {"rejected", "unconfirmed"}:
            record.state = "unconfirmed"
            record.issues = ["missing: not present in the latest successful collection"]
            record.revision += 1
            if record.job_id:
                job = db.get(Job, record.job_id)
                if job and job.source_id == source.id:
                    job.status = "unconfirmed"
            record_event(db, record, "missing")
    if rows:
        source.last_vacancy_discovery_at = timestamp
    return {"records": len(seen), "published": published, "pending": pending}


def review_record(
    db,
    actor,
    record,
    *,
    revision,
    action,
    note,
    reference,
    changes=None,
    employer_confirmed=False,
    nursing_confirmed=False,
):
    require_operator(db, actor)
    note = clean(note, "Decision reason", 3000)
    reference = checked_url(reference)
    source = db.scalar(
        select(RecruitmentSource)
        .where(RecruitmentSource.id == record.source_id)
        .with_for_update(of=RecruitmentSource)
        .execution_options(populate_existing=True)
    )
    locked = db.scalar(
        select(VacancyRecord)
        .where(VacancyRecord.id == record.id)
        .with_for_update(of=VacancyRecord)
        .execution_options(populate_existing=True)
    )
    if not locked or locked.revision != revision:
        raise RecruitmentError("This vacancy changed. Reload and review the current record.")
    record = locked
    if action == "publish":
        if not collector_authorized(source) or source.health_status != "healthy":
            raise RecruitmentError(
                "Collection must be enabled for a currently approved, healthy source."
            )
        if utc(record.last_seen_at) < now() - FRESHNESS or (
            source.last_success_at and utc(record.last_seen_at) < utc(source.last_success_at)
        ):
            raise RecruitmentError("This record is no longer confirmed by the latest source check.")
        data = dict(record.normalized)
        for key, value in (changes or {}).items():
            if key not in EDITABLE or not isinstance(value, str) or len(value) > 30000:
                raise RecruitmentError("Unsupported vacancy correction.")
            data[key] = value.strip()
        data["country"] = data.get("country", "").upper()
        data["_review"] = {
            "employer_confirmed": employer_confirmed,
            "nursing_confirmed": nursing_confirmed,
            "changes": {key: data[key] for key in changes or {}},
            "reference": reference,
        }
        issues = validation_issues(
            data, source, employer_confirmed=employer_confirmed, nursing_confirmed=nursing_confirmed
        )
        if issues:
            raise RecruitmentError("; ".join(issues))
        record.normalized, record.issues = data, []
        _publish(db, record, record.last_seen_at)
        if record.state != "published":
            raise RecruitmentError(
                "Conflicting records remain. Reject the incorrect record or reconcile the evidence."
            )
    elif action == "reject":
        record.state = "rejected"
        if record.job_id:
            job = db.get(Job, record.job_id)
            if job:
                job.status = "unconfirmed"
    else:
        raise RecruitmentError("Choose publish or reject.")
    record.revision += 1
    record_event(db, record, action, actor=actor, note=note, reference=reference)
    db.commit()


def record_list(db, *, state="", source_id=None, page=1):
    query = select(VacancyRecord)
    if state in {"pending", "published", "rejected", "unconfirmed"}:
        query = query.where(VacancyRecord.state == state)
    if source_id:
        query = query.where(VacancyRecord.source_id == source_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(VacancyRecord.last_seen_at.desc(), VacancyRecord.id.desc())
            .offset((page - 1) * 25)
            .limit(25)
        )
    )
    return rows, total
