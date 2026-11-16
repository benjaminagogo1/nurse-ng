"""Consolidate legacy URL aliases while retaining job links and collection evidence."""

from collections import defaultdict

from sqlalchemy import select

from app.models.jobs import Job
from app.models.notifications import Notification
from app.models.opportunities import SavedOpportunity
from app.models.recruitment import RecruitmentSource
from app.models.vacancies import VacancyRecord
from app.services.job_aliases import retained_job
from app.services.recruitment import utc
from app.services.recruitment_fetch import url_key
from app.services.vacancies import _record_key, data_hash, digest, record_event
from app.services.vacancy_quality import canonical_vacancy_url


def _facts(data):
    # Collection URLs and timestamps may differ. Availability evidence must agree.
    index = data.get("_index", {})
    return data_hash(data), tuple(index.get(key) for key in (
        "closed", "accepting_applications", "deadline_unresolved", "deadline_timezone",
    ))


def _reconcile_member_history(db, keeper, aliases):
    """Preserve opt-outs, reminder progress and delivered/read notices across aliases."""
    ids = {keeper.id, *(job.id for job in aliases)}
    counts = {"saved_opportunities_moved": 0, "saved_opportunities_merged": 0,
              "notifications_retargeted": 0, "notifications_suppressed": 0}
    saves = defaultdict(list)
    for row in db.scalars(select(SavedOpportunity).where(SavedOpportunity.job_id.in_(ids))
                          .order_by(SavedOpportunity.user_id, SavedOpportunity.job_id)
                          .with_for_update(of=SavedOpportunity)):
        saves[row.user_id].append(row)
    for rows in saves.values():
        if all(row.job_id == keeper.id for row in rows):
            continue
        kept = next((row for row in rows if row.job_id == keeper.id), rows[0])
        reminded = [row.reminded_deadline for row in rows if row.reminded_deadline]
        matching = next((value for value in reminded if keeper.closes_at
                         and utc(value) == utc(keeper.closes_at)), None)
        kept.remind = all(row.remind for row in rows)  # Never override an explicit opt-out.
        kept.reminded_deadline = matching or (max(reminded, key=utc) if reminded else None)
        kept.created_at = min((row.created_at for row in rows), key=utc)
        kept.updated_at = max((row.updated_at for row in rows), key=utc)
        if kept.job_id != keeper.id:
            kept.job_id = keeper.id
            counts["saved_opportunities_moved"] += 1
        for row in rows:
            if row is not kept:
                db.delete(row)
                counts["saved_opportunities_merged"] += 1
    db.flush()
    notices = defaultdict(list)
    for notice in db.scalars(select(Notification).where(
            Notification.job_id.in_(ids), Notification.category == "opportunities",
            Notification.kind.in_(["opportunity_match", "deadline_reminder"]))
            .order_by(Notification.recipient_id, Notification.id)
            .with_for_update(of=Notification)):
        if notice.kind == "deadline_reminder":
            if not notice.deadline_at:
                continue
            key = f"deadline:{keeper.id}:{utc(notice.deadline_at).isoformat()}"
        else:
            key = f"match:{keeper.id}"
        notices[(notice.recipient_id, key)].append(notice)
    for (_, key), rows in notices.items():
        kept = next((row for row in rows if row.event_key == key), None)
        if kept is None:
            kept = min(rows, key=lambda row: (
                row.email_state != "sent", row.read_at is None, utc(row.created_at), row.id,
            ))
        if kept.job_id != keeper.id:
            kept.job_id, kept.event_key = keeper.id, key
            counts["notifications_retargeted"] += 1
        read = [row.read_at for row in rows if row.read_at]
        kept.read_at = max(read, key=utc) if read else None
        if any(row.email_state == "sent" for row in rows):
            kept.email_state, kept.email_to = "sent", ""
            kept.email_lease_token = kept.email_lease_until = kept.email_next_attempt = None
        for row in rows:
            if row is kept or row.job_id == keeper.id:
                continue
            if row.in_app or row.email_state in {"queued", "sending", "failed"}:
                counts["notifications_suppressed"] += 1
            row.in_app = False
            if row.email_state in {"queued", "sending", "failed"}:
                row.email_state = "skipped"
            row.email_to = ""
            row.email_lease_token = row.email_lease_until = row.email_next_attempt = None
    db.flush()
    return counts


def consolidate_duplicate_vacancies(db, *, dry_run=False):
    """One transaction; pause collectors and notification delivery before applying."""
    # Use the same source-before-job lock order as collection on row-locking databases.
    list(db.scalars(select(RecruitmentSource.id).order_by(RecruitmentSource.id)
                    .with_for_update(of=RecruitmentSource)))
    jobs = list(db.scalars(select(Job).where(Job.source_id.is_not(None))
                          .order_by(Job.created_at, Job.id).with_for_update(of=Job)))
    records = list(db.scalars(select(VacancyRecord)
                             .order_by(VacancyRecord.first_seen_at, VacancyRecord.id)
                             .with_for_update(of=VacancyRecord)))
    identities = {(record.source_id, record.record_key): record for record in records}
    groups = defaultdict(list)
    for job in jobs:
        url = job.normalized_data.get("announcement_url", "")
        if url and not job.normalized_data.get("_duplicate_of_job"):
            groups[canonical_vacancy_url(url)].append(job)
    result = {"groups": 0, "retired_jobs": 0, "duplicate_records": 0,
              "conflicts": 0, "merges": [], "saved_opportunities_moved": 0,
              "saved_opportunities_merged": 0, "notifications_retargeted": 0,
              "notifications_suppressed": 0}
    for canonical, group in groups.items():
        if len(group) < 2:
            continue
        key = url_key(canonical)
        keeper = next((job for job in group if job.external_key == key), group[0])
        ids = {job.id for job in group}
        evidence = [record for record in records if record.job_id in ids]
        expected = _facts(keeper.normalized_data)
        # Never resolve contradictory facts, rejected records or staff corrections by merging.
        if (not evidence or any(job.status != "open" or _facts(job.normalized_data) != expected
                                for job in group)
                or any(record.state != "published" or record.normalized.get("_review")
                       or _facts(record.normalized) != expected for record in evidence)
                or any(job.external_key == key and job.id not in ids for job in jobs)):
            result["conflicts"] += 1
            continue
        by_identity = defaultdict(list)
        for record in evidence:
            by_identity[(record.source_id, _record_key(record.raw_record))].append(record)
        if any(identity in identities and identities[identity] not in copies
               for identity, copies in by_identity.items()):
            result["conflicts"] += 1
            continue
        retired = [job for job in group if job.id != keeper.id]
        keeper.external_key = key
        for job in retired:
            job.status = "withdrawn"
            job.normalized_data = {**job.normalized_data, "_duplicate_of_job": str(keeper.id)}
        for identity, copies in by_identity.items():
            primary = min(copies, key=lambda record: (
                record.record_key != identity[1], record.job_id != keeper.id,
                utc(record.first_seen_at), record.id.hex,
            ))
            for record in copies:
                previous = {"job_id": str(record.job_id), "record_key": record.record_key,
                            "state": record.state, "issues": record.issues}
                record.normalized = {**record.normalized, "_announcement_key": digest({
                    "url": canonical,
                })}
                if record is primary:
                    identities.pop((record.source_id, record.record_key), None)
                    record.record_key = identity[1]
                    record.job_id = keeper.id
                    identities[identity] = record
                else:
                    record.state = "duplicate"
                    record.normalized = {**record.normalized, "_duplicate_of": str(primary.id)}
                    record.issues = ["duplicate: URL aliases of the same announcement and facts"]
                    result["duplicate_records"] += 1
                record.revision += 1
                record_event(db, record, "duplicate_consolidated", details={
                    "previous": previous, "canonical_url": canonical,
                    "canonical_job_id": str(keeper.id),
                    "retired_job_ids": [str(job.id) for job in retired],
                    "configuration_method": "operator_cli",
                })
        db.flush()
        result["groups"] += 1
        result["retired_jobs"] += len(retired)
        result["merges"].append({"canonical_url": canonical, "job_id": str(keeper.id),
                                 "retired_job_ids": [str(job.id) for job in retired]})
    # Also repair bookmarks/notices left by earlier runs of this maintenance command.
    aliases = defaultdict(list)
    for job in jobs:
        target = retained_job(db, job)
        if target and target.id != job.id:
            aliases[target.id].append(job)
    for keeper_id, copies in sorted(aliases.items()):
        counts = _reconcile_member_history(db, db.get(Job, keeper_id), copies)
        for name, count in counts.items():
            result[name] += count
        if any(counts.values()):
            record = next((row for row in records if row.job_id == keeper_id), None)
            if record:
                record_event(db, record, "saved_opportunities_reconciled", details={
                    **counts, "canonical_job_id": str(keeper_id),
                    "configuration_method": "operator_cli",
                })
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result
