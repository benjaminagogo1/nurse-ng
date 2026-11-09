"""Durable discovery queue with leases, fencing and a hard network-process deadline."""

import multiprocessing
import secrets
from collections import deque
from datetime import timedelta

from sqlalchemy import case, func, literal, or_, select, union_all, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recruitment import (
    DiscoverySchedule,
    DiscoveryTask,
    RecruitmentOrganization,
    RecruitmentSource,
    SourceEvent,
)
from app.services.recruitment import checked_url, event, now, register_candidate, utc
from app.services.recruitment_activation import POLICY_VERSION, apply_assessment, context, eligible
from app.services.recruitment_discovery import execute_discovery
from app.services.recruitment_fetch import in_scope, origin
from app.services.vacancies import collector_authorized, ingest_page, mark_source_unconfirmed

TASK_SECONDS = 45
LEASE_SECONDS = 90
MAX_ATTEMPTS = 3
NETWORK_COOLDOWN_SECONDS = 60


def _nigerian_source():
    """Search targeting affects queue priority, never verified country or publication."""
    return or_(
        RecruitmentOrganization.country_code == "NG",
        select(SourceEvent.id)
        .where(
            SourceEvent.source_id == RecruitmentSource.id,
            SourceEvent.kind.in_(["discovered", "discovery_target"]),
            SourceEvent.details["evidence"]["target_country"].as_string() == "NG",
        )
        .exists(),
    )


def enqueue_due(db: Session) -> int:
    timestamp = now()
    outstanding = (
        db.scalar(
            select(func.count())
            .select_from(DiscoveryTask)
            .where(
                DiscoveryTask.status.in_(["queued", "running"]),
            )
        )
        or 0
    )
    room = max(0, settings.recruitment_pending_task_limit - outstanding)
    added = 0
    # Consider schedules and sources together so worldwide schedules cannot fill
    # the queue ahead of due Nigerian source checks. Ignore already queued items.
    due = union_all(
        select(
            DiscoverySchedule.id.label("id"),
            literal("schedule").label("kind"),
            DiscoverySchedule.country_code.label("country"),
            DiscoverySchedule.next_run_at.label("due_at"),
        ).where(
            DiscoverySchedule.enabled.is_(True),
            DiscoverySchedule.next_run_at <= timestamp,
            ~select(DiscoveryTask.id)
            .where(
                DiscoveryTask.schedule_id == DiscoverySchedule.id,
                DiscoveryTask.active_key.is_not(None),
            )
            .exists(),
        ),
        select(
            RecruitmentSource.id,
            literal("source"),
            case((_nigerian_source(), "NG"), else_=RecruitmentOrganization.country_code),
            RecruitmentSource.next_check_at,
        )
        .join(RecruitmentOrganization)
        .where(
            RecruitmentSource.next_check_at <= timestamp,
            RecruitmentSource.automation_status == "monitoring",
            RecruitmentSource.verification_status.not_in(["rejected", "revoked"]),
            ~select(DiscoveryTask.id)
            .where(
                DiscoveryTask.source_id == RecruitmentSource.id,
                DiscoveryTask.active_key.is_not(None),
            )
            .exists(),
        ),
    ).subquery()
    groups = [
        deque(
            db.execute(
                select(due)
                .where(condition)
                .order_by(
                    due.c.due_at,
                    due.c.id,
                )
                .limit(room)
            )
        )
        for condition in (due.c.country == "NG", due.c.country != "NG")
    ]
    admitted = db.scalar(select(func.count()).select_from(DiscoveryTask)) or 0
    candidates = []
    for slot in range(room):
        preferred = 1 if (admitted + slot) % 5 == 4 else 0
        group = groups[preferred] or groups[1 - preferred]
        if not group:
            break
        candidates.append(group.popleft())
    schedules = list(
        db.scalars(
            select(DiscoverySchedule)
            .where(
                DiscoverySchedule.id.in_([row.id for row in candidates if row.kind == "schedule"]),
                DiscoverySchedule.enabled.is_(True),
                DiscoverySchedule.next_run_at <= timestamp,
            )
            .order_by(DiscoverySchedule.next_run_at, DiscoverySchedule.id)
            .limit(room)
        )
    )
    for schedule in schedules:
        key = f"schedule:{schedule.id}"
        if db.scalar(select(DiscoveryTask.id).where(DiscoveryTask.active_key == key)):
            continue
        try:
            with db.begin_nested():
                claimed = db.execute(
                    update(DiscoverySchedule)
                    .where(
                        DiscoverySchedule.id == schedule.id,
                        DiscoverySchedule.next_run_at == schedule.next_run_at,
                        DiscoverySchedule.enabled.is_(True),
                    )
                    .values(next_run_at=timestamp + timedelta(hours=schedule.interval_hours))
                    .execution_options(synchronize_session=False)
                )
                if not claimed.rowcount:
                    continue
                db.add(
                    DiscoveryTask(
                        kind=schedule.provider,
                        schedule_id=schedule.id,
                        active_key=key,
                        available_at=timestamp,
                        payload={
                            "query": schedule.query,
                            "country_code": schedule.country_code,
                            "page": schedule.next_page,
                        },
                    )
                )
                db.flush()
            added += 1
        except IntegrityError:
            continue
    sources = list(
        db.scalars(
            select(RecruitmentSource)
            .where(
                RecruitmentSource.id.in_([row.id for row in candidates if row.kind == "source"]),
                RecruitmentSource.next_check_at <= timestamp,
                RecruitmentSource.automation_status == "monitoring",
                RecruitmentSource.verification_status.not_in(["rejected", "revoked"]),
            )
            .order_by(RecruitmentSource.next_check_at, RecruitmentSource.id)
            .limit(max(0, room - added))
        )
    )
    for source in sources:
        key = f"source:{source.id}"
        if db.scalar(select(DiscoveryTask.id).where(DiscoveryTask.active_key == key)):
            continue
        try:
            with db.begin_nested():
                claimed = db.execute(
                    update(RecruitmentSource)
                    .where(
                        RecruitmentSource.id == source.id,
                        RecruitmentSource.next_check_at == source.next_check_at,
                        RecruitmentSource.automation_status == "monitoring",
                    )
                    .values(next_check_at=timestamp + timedelta(days=1))
                    .execution_options(synchronize_session=False)
                )
                if not claimed.rowcount:
                    continue
                db.add(
                    DiscoveryTask(
                        kind="inspect",
                        source_id=source.id,
                        active_key=key,
                        available_at=timestamp,
                        payload={},
                    )
                )
                db.flush()
            added += 1
        except IntegrityError:
            continue
    db.commit()
    db.expire_all()
    return added


def claim_next(db: Session) -> DiscoveryTask | None:
    timestamp = now()
    for expired in list(
        db.scalars(
            select(DiscoveryTask).where(
                DiscoveryTask.status == "running",
                DiscoveryTask.lease_until <= timestamp,
            )
        )
    ):
        retry = expired.attempts < MAX_ATTEMPTS
        db.execute(
            update(DiscoveryTask)
            .where(
                DiscoveryTask.id == expired.id,
                DiscoveryTask.lease_token == expired.lease_token,
                DiscoveryTask.status == "running",
                DiscoveryTask.lease_until <= timestamp,
            )
            .values(
                status="queued" if retry else "failed",
                running_key=None,
                lease_token=None,
                active_key=expired.active_key if retry else None,
                available_at=timestamp,
                finished_at=None if retry else timestamp,
                outcome="lease_expired",
                message="A worker stopped before completing this check.",
            )
            .execution_options(synchronize_session=False)
        )
        # SQLite returns naive timestamps. Let SQL compare lease times and reload
        # the object rather than evaluating aware-vs-naive datetime predicates in Python.
        db.expire(expired)
    db.commit()
    pause_until = db.scalar(select(func.max(DiscoveryTask.network_pause_until)))
    if pause_until and utc(pause_until) > timestamp:
        return None
    midnight = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        db.scalar(
            select(func.sum(DiscoveryTask.attempts)).where(
                DiscoveryTask.started_at >= midnight,
            )
        )
        or 0
    )
    if used >= settings.recruitment_daily_task_limit:
        return None
    if db.scalar(select(DiscoveryTask.id).where(DiscoveryTask.running_key == "network")):
        return None
    local_task = or_(
        select(DiscoverySchedule.id)
        .where(
            DiscoverySchedule.id == DiscoveryTask.schedule_id,
            DiscoverySchedule.country_code == "NG",
        )
        .exists(),
        select(RecruitmentSource.id)
        .join(RecruitmentOrganization)
        .where(
            RecruitmentSource.id == DiscoveryTask.source_id,
            _nigerian_source(),
        )
        .exists(),
    )
    # Four of every five attempt slots prefer Nigeria. The fifth prefers other
    # countries; either group can use a slot when the preferred queue is empty.
    preferred = ~local_task if used % 5 == 4 else local_task
    active_source = (
        select(RecruitmentSource.id)
        .where(
            RecruitmentSource.id == DiscoveryTask.source_id,
            RecruitmentSource.verification_status == "approved",
            RecruitmentSource.collection_adapter != "",
        )
        .exists()
    )
    task = db.scalar(
        select(DiscoveryTask)
        .where(
            DiscoveryTask.status == "queued",
            DiscoveryTask.available_at <= timestamp,
        )
        .order_by(
            case((preferred, 0), else_=1),
            case((active_source, 0), (DiscoveryTask.attempts == 0, 1), else_=2),
            DiscoveryTask.available_at,
            DiscoveryTask.id,
        )
        .limit(1)
    )
    if task is None:
        return None
    try:
        changed = db.execute(
            update(DiscoveryTask)
            .where(
                DiscoveryTask.id == task.id,
                DiscoveryTask.status == "queued",
            )
            .values(
                status="running",
                running_key="network",
                lease_token=secrets.token_hex(16),
                lease_until=timestamp + timedelta(seconds=LEASE_SECONDS),
                attempts=DiscoveryTask.attempts + 1,
                started_at=timestamp,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        db.refresh(task)
        return task
    except IntegrityError:
        # Another process won the global network lease.
        db.rollback()
        return None


def _child_execute(pipe, kind: str, payload: dict) -> None:
    try:
        result = execute_discovery(
            kind,
            payload,
            search_key=settings.recruitment_search_key,
            search_permission=settings.recruitment_search_permission_reference,
        )
        pipe.send(result)
    except Exception:
        # Never persist arbitrary exception text, URLs containing credentials, or API keys.
        pipe.send(
            {
                "ok": False,
                "outcome": "processing_error",
                "retryable": False,
                "message": "The adapter failed to process the response. Review its format.",
            }
        )
    finally:
        pipe.close()


def isolated_execute(kind: str, payload: dict) -> dict:
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=_child_execute, args=(sending, kind, payload), daemon=True)
    try:
        process.start()
        sending.close()
        if receiving.poll(TASK_SECONDS):
            try:
                return receiving.recv()
            except EOFError:
                return {
                    "ok": False,
                    "outcome": "processing_error",
                    "retryable": True,
                    "message": "The isolated page checker stopped unexpectedly.",
                }
        return {
            "ok": False,
            "outcome": "timeout",
            "retryable": True,
            "message": "The isolated page check exceeded its 45-second deadline.",
        }
    finally:
        receiving.close()
        sending.close()
        if process.pid:
            process.join(timeout=0.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)


def _inspection_allowed(source: RecruitmentSource | None) -> bool:
    return bool(
        source
        and source.automation_status == "monitoring"
        and source.verification_status not in {"rejected", "revoked"}
    )


def apply_result(db: Session, task_id, token: str, payload: dict, result: dict) -> bool:
    """Fence stale workers BEFORE any candidate, source-state or audit mutation."""
    timestamp = now()
    task = db.get(DiscoveryTask, task_id, populate_existing=True)
    if not task:
        return False
    changed = db.execute(
        update(DiscoveryTask)
        .where(
            DiscoveryTask.id == task_id,
            DiscoveryTask.lease_token == token,
            DiscoveryTask.status == "running",
            DiscoveryTask.lease_until > timestamp,
        )
        .values(running_key=None, lease_token=None, lease_until=None)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        return False
    db.refresh(task)
    source = (
        db.scalar(
            select(RecruitmentSource)
            .where(RecruitmentSource.id == task.source_id)
            .with_for_update(of=RecruitmentSource)
            .execution_options(populate_existing=True)
        )
        if task.source_id
        else None
    )
    schedule = (
        db.get(DiscoverySchedule, task.schedule_id, populate_existing=True)
        if task.schedule_id
        else None
    )
    if (
        task.source_id
        and (not _inspection_allowed(source) or source.revision != payload.get("revision"))
        or task.schedule_id
        and (not schedule or not schedule.enabled)
    ):
        result = {
            "ok": False,
            "outcome": "cancelled",
            "message": "The source or schedule changed before completion.",
        }
    if payload.get("collect_vacancies") and not collector_authorized(source):
        result = {
            "ok": False,
            "outcome": "cancelled",
            "message": "Source collection permission changed.",
        }
    task.status = "completed" if result.get("ok") else "failed"
    task.active_key = None
    task.finished_at = timestamp
    task.outcome = result.get("outcome", "processing_error")[:40]
    task.message = result.get("message", "")[:500]
    task.result_count = 0
    task.network_pause_until = timestamp + timedelta(
        seconds=max(
            NETWORK_COOLDOWN_SECONDS,
            result.get("retry_after", 900) if task.outcome == "rate_limited" else 0,
        )
    )
    if task.outcome == "cancelled":
        task.status = "cancelled"
    elif result.get("ok"):
        if schedule:
            schedule.next_page = result.get("next_page", schedule.next_page)
            for candidate in result.get("candidates", [])[:20]:
                _, created = register_candidate(db, **candidate, task_id=task.id)
                task.result_count += int(created)
        if source:
            previous = source.observed_url or source.original_url
            source.last_attempt_at = timestamp
            source.last_success_at = timestamp
            source.health_status = "healthy"
            source.failure_count = 0
            observed_hash = result.get("original_content_hash", result["content_hash"])
            if source.content_hash != observed_hash:
                source.last_changed_at = timestamp
            source.content_hash = observed_hash
            source.observed_url = checked_url(result["observed_url"])
            source.canonical_hint = (
                checked_url(result["canonical_hint"]) if result.get("canonical_hint") else ""
            )
            if (
                previous
                and origin(previous) != origin(source.observed_url)
                and source.verification_status == "approved"
            ):
                source.verification_status = "pending"
                source.permission_status = "unknown"
                source.approval_expires_at = None
                event(
                    db,
                    source,
                    "domain_changed",
                    task_id=task.id,
                    details={
                        "previous": previous,
                        "observed": source.observed_url,
                        "note": "Review the new domain association before collecting vacancies.",
                    },
                )
            if (
                source.verification_status == "approved"
                and source.reuse_url_prefix
                and not in_scope(source.observed_url, source.reuse_url_prefix)
            ):
                source.verification_status = "pending"
                source.permission_status = "unknown"
                source.approval_expires_at = None
                mark_source_unconfirmed(db, source.id)
                event(
                    db,
                    source,
                    "reuse_scope_changed",
                    task_id=task.id,
                    details={"observed": source.observed_url, "scope": source.reuse_url_prefix},
                )
            source.revision += 1
            automatically_activated = apply_assessment(db, source, result, timestamp, task.id)
            if result.get("activation_review") and not automatically_activated:
                task.message = (
                    "Automatic activation needs review: "
                    + "; ".join(result["activation_review"]["reasons"])[:440]
                )
            if (
                payload.get("collect_vacancies") or automatically_activated
            ) and collector_authorized(source):
                counts = ingest_page(db, source, result, timestamp)
                # Revisit bounded batches often enough to keep valid opportunities fresh.
                source.next_check_at = timestamp + timedelta(hours=6)
                task.message = (
                    f"Collected {counts['records']} vacancies; "
                    f"{counts['published']} publishable, {counts['pending']} need review."
                )
                if result.get("detail_errors"):
                    task.message += (
                        f" {len(result['detail_errors'])} detail pages deferred or unavailable."
                    )
                if counts.get("error"):
                    task.status, task.outcome = "failed", "extraction_error"
                    task.message = counts["error"][:500]
            event(
                db,
                source,
                "page_checked",
                task_id=task.id,
                reference=source.original_url,
                details={
                    key: result.get(key)
                    for key in (
                        "title",
                        "observed_url",
                        "canonical_hint",
                        "content_hash",
                        "original_content_hash",
                        "links",
                        "terms_links",
                        "document_links",
                        "sitemap_note",
                    )
                },
            )
            # Bound expansion: institution/search pages can reveal recruitment pages;
            # those pages are inspected but cannot recursively generate an endless crawl.
            if not payload.get("collect_vacancies") and source.source_type in {
                "institution_site",
                "search_candidate",
            }:
                org = source.organization
                for link in result.get("links", [])[:3]:
                    if (
                        automatically_activated
                        and source.collection_adapter == "factual_index"
                        and in_scope(link["url"], source.vacancy_url_prefix)
                    ):
                        continue
                    _, created = register_candidate(
                        db,
                        identity_key=org.identity_key,
                        name=org.name,
                        category=org.category,
                        country_code=org.country_code,
                        location=org.location,
                        website_url=org.website_url,
                        source_url=link["url"],
                        discovered_via="institution_link",
                        reference=link.get("reference", source.original_url),
                        source_type="recruitment_page",
                        organization=org,
                        task_id=task.id,
                        evidence={"link_label": link["label"], "observed_on": source.observed_url},
                    )
                    task.result_count += int(created)
    else:
        if source:
            if payload.get("collect_vacancies") or source.approval_mode == "automatic":
                mark_source_unconfirmed(db, source.id)
            if payload.get("automatic_activation"):
                apply_assessment(
                    db,
                    source,
                    {
                        "activation_review": {
                            "status": "needs_review",
                            "policy_version": POLICY_VERSION,
                            "evidence": {},
                            "reasons": ["Automatic checks could not complete: " + task.outcome],
                        }
                    },
                    timestamp,
                    task.id,
                )
            source.last_attempt_at = timestamp
            source.health_status = task.outcome[:30]
            source.failure_count += 1
            source.revision += 1
            event(
                db,
                source,
                "check_failed",
                task_id=task.id,
                reference=source.original_url,
                details={"outcome": task.outcome, "message": task.message},
            )
        if result.get("retryable") and task.attempts < MAX_ATTEMPTS:
            task.status = "queued"
            task.active_key = (
                f"source:{task.source_id}" if task.source_id else f"schedule:{task.schedule_id}"
            )
            task.available_at = timestamp + timedelta(minutes=5 * 2 ** (task.attempts - 1))
            task.finished_at = None
    db.commit()
    return True


def run_next(db: Session, *, executor=None) -> DiscoveryTask | None:
    task = claim_next(db)
    if task is None:
        return None
    identifier, token, kind = task.id, task.lease_token, task.kind
    payload = dict(task.payload)
    if task.source_id:
        source = db.get(RecruitmentSource, task.source_id, populate_existing=True)
        if _inspection_allowed(source):
            payload = {
                "url": source.original_url,
                "source_type": source.source_type,
                "revision": source.revision,
                "collect_vacancies": collector_authorized(source),
                "reuse_url_prefix": source.reuse_url_prefix,
                "collection_adapter": source.collection_adapter,
                "page_offset": max(0, source.revision - 1) * 4,
            }
            if eligible(source):
                payload["automatic_activation"] = context(source, db)
                # Recheck independent identity and current reuse evidence on every collection.
                payload["collect_vacancies"] = False
        else:
            apply_result(db, identifier, token, payload, {"ok": False, "outcome": "cancelled"})
            return task
    if task.schedule_id:
        schedule = db.get(DiscoverySchedule, task.schedule_id, populate_existing=True)
        if not schedule or not schedule.enabled:
            apply_result(db, identifier, token, payload, {"ok": False, "outcome": "cancelled"})
            return task
    # End the read transaction before slow network work. No ORM objects go to the child.
    db.commit()
    try:
        result = (executor or isolated_execute)(kind, payload)
    except Exception:
        result = {
            "ok": False,
            "outcome": "processing_error",
            "retryable": False,
            "message": "The page checker failed; no source was approved.",
        }
    try:
        apply_result(db, identifier, token, payload, result)
    except Exception:
        db.rollback()
        apply_result(
            db,
            identifier,
            token,
            payload,
            {
                "ok": False,
                "outcome": "processing_error",
                "retryable": False,
                "message": "Invalid adapter output. No partial discovery was committed.",
            },
        )
    return db.get(DiscoveryTask, identifier, populate_existing=True)
