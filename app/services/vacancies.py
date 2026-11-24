"""Approved-source vacancy ingestion and explicit exception review, in one transaction.

Snapshot, normalized record, review outcome and public Job are distinct
records. Publication requires current collection authority and usable facts.
Stable announcement keys and duplicate review preserve links/history on retries.
"""

import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.jobs import Job
from app.models.recruitment import RecruitmentSource
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.services.opportunities import EARLY_CAREER, relevant_opportunity
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
from app.services.vacancy_quality import (
    canonical_vacancy_record,
    canonical_vacancy_url,
    non_vacancy_reason,
)

FRESHNESS = timedelta(hours=48)
COLLECTORS = {
    "jsonld": "Structured job data",
    "announcements": "Announcement pages and linked opportunities",
    "factual_index": "Factual listings with original announcement links",
}
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
    data = {key: data for key, data in value.items() if not key.startswith("_")}
    if data.get("announcement_url"):
        data["announcement_url"] = canonical_vacancy_url(data["announcement_url"])
    return digest(data)


def collector_authorized(source) -> bool:
    return bool(
        source
        and collection_authorized(source)
        and source.collection_method == "html"
        and source.collection_adapter in COLLECTORS
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
    from app.services.factual_opportunities import index_authorized

    if not index_authorized(source) and (
        source.permission_status != "permitted" or not reuse_authorized(source)
    ):
        blockers.append(
            "Verified reuse evidence must cover collection, original snapshot retention "
            "and republication within the approved URL scope."
        )
    if source.automation_status != "monitoring":
        blockers.append("Automatic collection is paused or set to administrator-assisted mode.")
    if source.collection_method != "html":
        blockers.append("The available collector requires approval for website collection.")
    if source.collection_adapter not in COLLECTORS or not source.deadline_timezone:
        blockers.append("Configure a vacancy collector and deadline timezone after approval.")
    if not source.vacancy_url_prefix or not in_scope(
        source.vacancy_url_prefix, source.reuse_url_prefix
    ):
        blockers.append("The collector URL scope must be within the recorded permission scope.")
    return blockers


def configure_collector(
    db, actor, source, *, revision, enabled, url_prefix, timezone, note, reference, adapter="jsonld"
):
    require_operator(db, actor)
    note = clean(note, "Configuration reason and permission scope", 3000)
    reference = checked_url(reference)
    if adapter not in COLLECTORS:
        raise RecruitmentError("Choose a supported collection format.")
    if enabled:
        if adapter == "factual_index" or source.reuse_basis == "factual_index":
            raise RecruitmentError(
                "Use 'Approve and start collection' to configure factual listings. "
                "Full-description collection requires recorded reuse permission."
            )
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
            approval_mode="staff",
            collection_adapter=adapter if enabled else "",
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
        return digest({"url": canonical_vacancy_url(url)})
    return digest(raw)


def _hold_duplicate(db, record) -> bool:
    """Keep independent source evidence while asking staff to review identical facts once."""
    url = record.normalized.get("announcement_url")
    if not url or record.normalized.get("_review"):
        return False
    candidates = db.scalars(
        select(VacancyRecord).where(
            VacancyRecord.id != record.id,
            VacancyRecord.state.in_(["pending", "published"]),
            or_(
                VacancyRecord.normalized["announcement_url"].as_string() == url,
                VacancyRecord.normalized["_announcement_key"].as_string()
                == digest({"url": canonical_vacancy_url(url)}),
            ),
        ).order_by(VacancyRecord.first_seen_at, VacancyRecord.id)
    )
    for other in candidates:
        if other.state == "pending" and (
            utc(other.first_seen_at), other.id.hex
        ) > (utc(record.first_seen_at), record.id.hex):
            continue
        if data_hash(other.normalized) != data_hash(record.normalized):
            continue
        record.state = "duplicate"
        record.normalized = {**record.normalized, "_duplicate_of": str(other.id)}
        record.issues = ["duplicate: the same announcement and facts already have a review record"]
        return True
    return False


def _publish(db, record, timestamp):
    """Exact announcement URLs deduplicate; conflicting records need a human decision."""
    from app.services.recruitment_fetch import url_key

    data, source = record.normalized, record.source
    canonical = canonical_vacancy_url(data["announcement_url"])
    key = url_key(canonical)
    job = db.scalar(select(Job).where(Job.external_key == key).with_for_update(of=Job))
    if job is None:
        # Upgrade identities from earlier collections without replacing saved job links.
        candidates = db.scalars(select(Job).where(
            Job.source_id.is_not(None),
            or_(Job.id == record.job_id, Job.title == data["title"]),
        ).with_for_update(of=Job))
        job = next((item for item in candidates if canonical_vacancy_url(
            item.normalized_data.get("announcement_url", "")
        ) == canonical), None)
        if job is not None:
            job.external_key = key
    if job:
        competitors = list(
            db.scalars(
                select(VacancyRecord).where(
                    VacancyRecord.job_id == job.id,
                    VacancyRecord.id != record.id,
                    VacancyRecord.state.not_in(["rejected", "duplicate"]),
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
        job = Job(external_key=key, employer_user_id=None, created_at=timestamp)
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
    timezone = data.get("_index", {}).get("deadline_timezone") or source.deadline_timezone
    job.closes_at = parse_date(data["closing_date"], timezone, closing=True)
    job.opens_at = parse_date(data.get("opening_date", ""), timezone)
    job.posted_at = parse_date(data["publication_date"], timezone) or record.first_seen_at
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
            adapter=source.collection_adapter + "-v1",
        )
        db.add(snapshot)
        db.flush()
    try:
        if source.collection_adapter == "factual_index":
            envelope = json.loads(body)
            if envelope["url"] != result["observed_url"]:
                raise RecruitmentError("Fact snapshot URL does not match the observed page.")
            rows = envelope["records"]
        else:
            rows = extract_records(body)
        if source.collection_adapter == "announcements" and not rows:
            from app.services.announcement_extraction import extract_announcements

            rows = extract_announcements(body, result["observed_url"])
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
    # Comment/tracking aliases of one object are also duplicates, not conflicting facts.
    versions = {}
    for raw, key in zip(rows, keys, strict=True):
        versions.setdefault(key, set()).add(digest(canonical_vacancy_record(raw)))
    duplicated = {key for key, hashes in versions.items() if len(hashes) > 1}
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
        if record is None and not raw.get("identifier") and raw.get("url"):
            candidates = db.scalars(select(VacancyRecord).where(
                VacancyRecord.source_id == source.id
            ).order_by(VacancyRecord.first_seen_at, VacancyRecord.id))
            record = next((item for item in candidates
                           if not item.raw_record.get("identifier") and canonical_vacancy_url(
                               item.raw_record.get("url", "")
                           ) == canonical_vacancy_url(raw["url"])), None)
            if record is not None:
                record.record_key = key
        raw_hash = digest(raw)
        previous_state = record.state if record else None
        previous_normalized = record.normalized if record else {}
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
            record.raw_record, record.content_hash = raw, raw_hash
        # Reapply extraction fixes even when the publisher's raw facts did not change.
        # Staff clarifications survive only while their original evidence is unchanged.
        refreshed = normalize(raw)
        if not changed:
            refreshed.update({key: value for key, value in previous_normalized.items()
                              if key.startswith("_")})
            refreshed.update({key: value for key, value in
                              refreshed.get("_review", {}).get("changes", {}).items()
                              if key in EDITABLE})
        normalized_changed = data_hash(previous_normalized) != data_hash(refreshed)
        record.normalized = refreshed
        data = record.normalized
        if "_duplicate_of" in data:
            data = {key: value for key, value in data.items() if key != "_duplicate_of"}
            record.normalized = data
        if data.get("announcement_url"):
            data = {**data, "_announcement_key": digest({
                "url": canonical_vacancy_url(data["announcement_url"]),
            })}
            record.normalized = data
        if source.collection_adapter == "factual_index":
            data = {**data, "_index": raw["_index"]}
            record.normalized = data
        elif source.approval_mode == "automatic":
            evidence = source.activation_review["evidence"]
            data = {
                **data,
                "_licence": {
                    "url": evidence["licence_url"],
                    "name": evidence["licence_name"],
                    "attribution": source.organization.name,
                    "source_url": source.original_url,
                },
            }
            record.normalized = data
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
        if record.state == "pending" and record.issues:
            _hold_duplicate(db, record)
        if record.state != "rejected" and record.state != "duplicate" and not record.issues:
            _publish(db, record, timestamp)
        elif record.job_id:
            job = db.get(Job, record.job_id)
            if job and job.source_id == source.id:
                job.status = "unconfirmed"
        if changed or normalized_changed or record.state != previous_state:
            record_event(db, record, "collected", details={
                "state": record.state,
                "normalization_changed": normalized_changed and not changed,
            })
        published += record.state == "published"
        pending += record.state == "pending"
        db.flush()
    missing_query = select(VacancyRecord).where(VacancyRecord.source_id == source.id)
    if source.collection_adapter in {"announcements", "factual_index"}:
        # A bounded page batch cannot establish that unvisited announcements disappeared.
        missing_query = missing_query.join(VacancySnapshot).where(
            VacancySnapshot.observed_url == result["observed_url"]
        )
    for record in db.scalars(missing_query):
        if record.record_key not in seen and record.state not in {
            "rejected", "unconfirmed", "duplicate",
        }:
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
    counts = {"records": len(seen), "published": published, "pending": pending}
    for detail in result.get("detail_pages", [])[:4]:
        if source.collection_adapter not in {"announcements", "factual_index"}:
            raise RecruitmentError("Unexpected detail-page collection.")
        if not in_scope(detail["observed_url"], source.vacancy_url_prefix):
            raise RecruitmentError("Detail page outside collection scope.")
        child = ingest_page(
            db, source, {k: v for k, v in detail.items() if k != "detail_pages"}, timestamp
        )
        for key in counts:
            counts[key] += child[key]
        if child.get("error"):
            counts["error"] = child["error"]
    for failed in result.get("detail_errors", [])[:4]:
        for record in db.scalars(
            select(VacancyRecord)
            .join(VacancySnapshot)
            .where(
                VacancyRecord.source_id == source.id,
                VacancySnapshot.observed_url == failed["url"],
            )
        ):
            if record.job_id:
                job = db.get(Job, record.job_id)
                if job and job.source_id == source.id:
                    job.status = "unconfirmed"
        event(db, source, "detail_check_failed", reference=failed["url"], details=failed)
    return counts


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


def reconcile_pending_quality(db, *, dry_run=False, exclude_unrelated=False):
    """Auditably remove obvious non-vacancies and duplicate pending work; retain evidence."""
    records = list(db.scalars(
        select(VacancyRecord).where(VacancyRecord.state == "pending")
        .order_by(VacancyRecord.first_seen_at, VacancyRecord.id)
    ))
    result = {"excluded": 0, "duplicates": 0}
    for record in records:
        if record.normalized.get("announcement_url"):
            record.normalized = {**record.normalized, "_announcement_key": digest({
                "url": canonical_vacancy_url(record.normalized["announcement_url"]),
            })}
    db.flush()
    for record in records:
        if record.normalized.get("_review"):
            continue
        reason = non_vacancy_reason(record.normalized.get("title", ""),
                                    record.normalized.get("announcement_url", ""))
        if (not reason and exclude_unrelated and record.normalized.get("_index")
                and not relevant_opportunity(record.normalized)
                and not (not record.normalized.get("country")
                         and EARLY_CAREER.search(record.normalized.get("title", "")))):
            reason = "relevance: outside health, nursing and Nigerian early-career opportunities"
        if reason:
            record.state = "rejected"
            record.issues = [reason]
            result["excluded"] += 1
            action = "quality_excluded"
        elif _hold_duplicate(db, record):
            result["duplicates"] += 1
            action = "duplicate_held"
        else:
            continue
        record.revision += 1
        record_event(db, record, action, details={"issues": record.issues})
        db.flush()
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result


def reassess_incomplete_records(db, *, dry_run=False):
    """Apply current listing rules to fresh pending facts without inventing a new check."""
    result = {"published": 0, "still_pending": 0, "skipped_unavailable": 0}
    timestamp = now()
    for record in db.scalars(select(VacancyRecord).where(VacancyRecord.state == "pending")):
        source = record.source
        if (not collector_authorized(source) or source.health_status != "healthy"
                or not record.last_seen_at or utc(record.last_seen_at) < timestamp - FRESHNESS):
            result["skipped_unavailable"] += 1
            continue
        previous_issues = list(record.issues)
        # Conflicting identities require their existing review; rechecking metadata
        # cannot establish which of two contradictory source records is correct.
        if any(issue.startswith(("identifier:", "conflict:")) for issue in previous_issues):
            result["still_pending"] += 1
            continue
        review = record.normalized.get("_review", {})
        record.issues = validation_issues(
            record.normalized, source,
            employer_confirmed=review.get("employer_confirmed", False),
            nursing_confirmed=review.get("nursing_confirmed", False),
        )
        if not record.issues:
            _publish(db, record, utc(record.last_seen_at))
        if record.state == "published":
            result["published"] += 1
        else:
            result["still_pending"] += 1
        if record.state == "published" or record.issues != previous_issues:
            record.revision += 1
            record_event(db, record, "listing_reassessed", details={
                "previous_issues": previous_issues,
                "configuration_method": "operator_cli",
                "note": "Missing optional details no longer prevent listing. "
                        "Original observation time retained.",
            })
        db.flush()
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result


def record_list(db, *, state="", source_id=None, page=1):
    query = select(VacancyRecord)
    if state in {"pending", "published", "rejected", "unconfirmed", "duplicate"}:
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
