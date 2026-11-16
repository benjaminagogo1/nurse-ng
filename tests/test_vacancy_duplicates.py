"""Comment aliases must not multiply listings or erase evidence during maintenance."""

import base64
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.jobs import Job
from app.models.notifications import Notification
from app.models.opportunities import SavedOpportunity
from app.models.recruitment import RecruitmentSource
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.services import opportunity_watch as watch
from app.services import recruitment as registry
from app.services import vacancies
from app.services.announcement_extraction import announcement_links
from app.services.factual_opportunities import collect_index, factual_records
from app.services.jobs import list_open_jobs
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancy_duplicates import consolidate_duplicate_vacancies
from app.services.vacancy_extraction import normalize
from app.services.vacancy_quality import canonical_vacancy_url
from tests.helpers import csrf_from
from tests.test_discussions import as_member
from tests.test_vacancy_ingestion import (  # noqa: F401
    collect,
    no_cooldown,
    page_result,
    posting,
    source,
    staff,
)

HOST = "https://hospital.example.ng"
URL = HOST + "/jobs/nurse-123"


@pytest.mark.parametrize(("suffix", "expected"), [
    ("?replytocom=231#respond", ""),
    ("?%72eplytocom=231&utm_source=notice&FBCLID=123#respond", ""),
    ("?job_id=123&replytocom=231&utm_source=notice", "?job_id=123"),
    ("?replytocom=231&job_id=456&page=2&lang=en", "?job_id=456&page=2&lang=en"),
    ("?id=one%26two&replytocom=231&empty=", "?id=one%26two&empty="),
])
def test_comment_navigation_is_removed_without_discarding_job_parameters(suffix, expected):
    assert canonical_vacancy_url(URL + suffix) == URL + expected


@pytest.mark.parametrize("channels", [False, True])
def test_discovery_visits_each_announcement_once_and_does_not_revisit_current_page(channels):
    body = b'''<main>
        <a href="?replytocom=99#respond">Registered Nurse</a>
        <a href="/jobs/other?replytocom=10#respond">Registered Nurse</a>
        <a href="/jobs/other?replytocom=11">Registered Nurse</a>
        <a href="/jobs/other?utm_source=email">Registered Nurse</a>
        <a href="/jobs/other">Registered Nurse</a>
        <a href="/jobs/view?job_id=1&amp;replytocom=12">Nurse</a>
        <a href="/jobs/view?job_id=2&amp;replytocom=13">Nurse</a>
    </main>'''
    links = announcement_links(body, URL + "?replytocom=98", HOST, include_channels=channels)
    assert links == [HOST + "/jobs/other", HOST + "/jobs/view?job_id=1",
                     HOST + "/jobs/view?job_id=2"]


def test_factual_collection_does_not_spend_requests_on_a_selected_channel_alias():
    page = FetchedPage(URL + "?replytocom=11", 200, "text/html", b'''<main>
        <h1>Registered Nurse</h1><p>Apply in Nigeria.</p>
        <a href="/jobs/nurse-123">Registered Nurse</a>
        <a href="/jobs/other?replytocom=12">Registered Nurse</a>
        <a href="/jobs/other?utm_source=mail">Registered Nurse</a>
    </main>''')

    class Fetcher:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(url)
            return FetchedPage(url, 200, "text/html", b'''<main>
                <h1>Registered Nurse</h1><p>Apply in Nigeria.</p>
                <a href="/jobs/nurse-123?replytocom=77">Registered Nurse</a>
            </main>''')

    fetcher = Fetcher()
    result = collect_index({}, page, fetcher, {
        "scope": HOST, "organisation": "Example Hospital", "collection_channel": URL,
    })
    assert fetcher.calls == [HOST + "/jobs/other"]
    assert len(result["detail_pages"]) == 1


@pytest.mark.parametrize("identifier", [None, {"value": "nurse-123"}])
def test_alias_copies_in_one_page_publish_once_and_retain_original_snapshot(
    db_session, source, identifier,  # noqa: F811
):
    raw = posting(identifier=identifier, url=URL + "?replytocom=231#respond")
    rows = [raw, {**raw, "url": URL}, {**raw, "url": URL + "?utm_source=mail"}]
    collect(db_session, source, rows)
    assert len(list_open_jobs(db_session)) == 1
    records = list(db_session.scalars(select(VacancyRecord)))
    assert len(records) == 1 and records[0].issues == []
    assert records[0].raw_record == raw
    assert db_session.scalar(select(VacancySnapshot)).body == base64.b64decode(
        page_result(rows)["body_base64"]
    )


def test_alias_deduplication_retains_page_salary_for_one_structured_job():
    raw = posting(url=URL + "?replytocom=231")
    result = page_result([raw, {**raw, "url": URL}])
    body = base64.b64decode(result["body_base64"]) + b"<p>Salary: NGN 200,000 monthly</p>"
    records = factual_records(FetchedPage(URL, 200, "text/html", body), {
        "scope": HOST, "organisation": "Example Hospital",
    })
    assert len(records) == 1
    assert normalize(records[0])["salary"] == {
        "currency": "NGN", "unit": "MONTH", "value": "200000",
    }


def test_differing_facts_on_aliases_still_require_review(db_session, source):  # noqa: F811
    raw = posting(identifier=None)
    collect(db_session, source, [raw, {**raw, "url": URL + "?replytocom=1",
                                     "validThrough": "2030-12-31"}])
    assert list_open_jobs(db_session) == []
    record = db_session.scalar(select(VacancyRecord))
    assert record.state == "pending"
    assert any(issue.startswith("identifier:") for issue in record.issues)


def test_distinct_job_query_parameters_remain_separate_jobs(db_session, source):  # noqa: F811
    collect(db_session, source, [
        posting(identifier=None, url=URL + "?job_id=1&replytocom=10"),
        posting(identifier=None, url=URL + "?job_id=2&replytocom=11"),
    ])
    assert len(list_open_jobs(db_session)) == 2
    assert db_session.scalar(select(func.count()).select_from(VacancyRecord)) == 2


def legacy_collection(db, item, monkeypatch, *, urls=None, deadline=None):
    """Create the rows produced before comment navigation was normalized."""
    urls = urls or [URL, URL + "?replytocom=1#respond", URL + "?replytocom=2#respond"]
    rows = [posting(identifier=None, url=url, **({"validThrough": deadline} if deadline else {}))
            for url in urls]
    with monkeypatch.context() as legacy:
        legacy.setattr(vacancies, "canonical_vacancy_url", lambda value: value)
        collect(db, item, rows)
    jobs = list(db.scalars(select(Job).order_by(Job.created_at, Job.id)))
    assert len(list_open_jobs(db)) == len(urls)
    return jobs, rows


def evidence_snapshot(db):
    return {
        "jobs": [(job.id, job.status, job.external_key, deepcopy(job.normalized_data),
                  job.confirmed_at) for job in db.scalars(select(Job).order_by(Job.id))],
        "records": [(record.id, record.state, record.revision, record.record_key, record.job_id,
                     deepcopy(record.raw_record), deepcopy(record.normalized))
                    for record in db.scalars(select(VacancyRecord).order_by(VacancyRecord.id))],
        "snapshots": [(snapshot.id, snapshot.body) for snapshot in db.scalars(
            select(VacancySnapshot).order_by(VacancySnapshot.id))],
        "events": [event.id for event in db.scalars(
            select(VacancyEvent).order_by(VacancyEvent.id))],
    }


def test_cleanup_preview_changes_nothing_and_apply_keeps_history_and_old_links(
    db_session, source, staff, client, monkeypatch,  # noqa: F811
):
    jobs, rows = legacy_collection(db_session, source, monkeypatch)
    keeper, retired = jobs[0], jobs[1:]
    saved = SavedOpportunity(user_id=staff.id, job_id=retired[0].id, remind=False)
    db_session.add(saved)
    db_session.commit()
    before = evidence_snapshot(db_session)
    preview = consolidate_duplicate_vacancies(db_session, dry_run=True)
    assert preview["groups"] == 1 and preview["retired_jobs"] == 2
    assert preview["duplicate_records"] == 2 and preview["conflicts"] == 0
    assert evidence_snapshot(db_session) == before
    assert consolidate_duplicate_vacancies(db_session) == preview
    assert [job.id for job in list_open_jobs(db_session)] == [keeper.id]
    after = evidence_snapshot(db_session)
    assert len(after["jobs"]) == len(before["jobs"])
    assert [record[0] for record in after["records"]] == [record[0] for record in before["records"]]
    assert [record[5] for record in after["records"]] == [record[5] for record in before["records"]]
    assert after["snapshots"] == before["snapshots"]
    assert set(before["events"]) < set(after["events"])
    events = list(db_session.scalars(select(VacancyEvent).where(
        VacancyEvent.action == "duplicate_consolidated")))
    assert len(events) == 3
    assert all(event.details["canonical_job_id"] == str(keeper.id) for event in events)
    assert db_session.get(SavedOpportunity, (staff.id, retired[0].id)) is None
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)).remind is False
    for job in retired:
        response = client.get(f"/jobs/{job.id}", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == f"/jobs/{keeper.id}"
        assert client.get(f"/jobs/{job.id}").status_code == 200
    assert consolidate_duplicate_vacancies(db_session)["groups"] == 0
    # A real source update must not conflict with archived copies or resurrect their jobs.
    changed = [{**raw, "validThrough": "2030-12-31"} for raw in rows]
    collect(db_session, source, changed)
    assert [job.id for job in list_open_jobs(db_session)] == [keeper.id]
    assert all(db_session.get(Job, job.id).status == "withdrawn" for job in retired)
    assert db_session.get(Job, keeper.id).normalized_data["closing_date"] == "2030-12-31"
    # Old links apply the retained source's current permission checks.
    source.verification_status = "revoked"
    db_session.commit()
    assert client.get(f"/jobs/{retired[0].id}", follow_redirects=False).status_code == 404


def test_cleanup_upgrades_alias_only_history_without_changing_the_kept_job_id(
    db_session, source, monkeypatch,  # noqa: F811
):
    jobs, _ = legacy_collection(db_session, source, monkeypatch, urls=[
        URL + "?replytocom=1#respond", URL + "?replytocom=2#respond",
    ])
    assert consolidate_duplicate_vacancies(db_session)["retired_jobs"] == 1
    collect(db_session, source, [posting(identifier=None)])
    assert [job.id for job in list_open_jobs(db_session)] == [jobs[0].id]
    assert db_session.scalar(select(func.count()).select_from(VacancyRecord)) == 2
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert consolidate_duplicate_vacancies(db_session)["groups"] == 0


@pytest.mark.parametrize("difference", ["facts", "review", "availability", "rejected"])
def test_cleanup_does_not_overwrite_disagreement_or_staff_decisions(
    db_session, source, monkeypatch, difference,  # noqa: F811
):
    jobs, _ = legacy_collection(db_session, source, monkeypatch)
    record = db_session.scalar(select(VacancyRecord).where(VacancyRecord.job_id == jobs[1].id))
    if difference == "facts":
        jobs[1].normalized_data = {**jobs[1].normalized_data, "closing_date": "2030-12-31"}
    elif difference == "review":
        record.normalized = {**record.normalized, "_review": {"employer_confirmed": True}}
    elif difference == "availability":
        record.normalized = {**record.normalized, "_index": {"closed": True}}
    else:
        record.state = "rejected"
    db_session.commit()
    before = evidence_snapshot(db_session)
    result = consolidate_duplicate_vacancies(db_session)
    assert result["groups"] == 0 and result["conflicts"] == 1
    assert evidence_snapshot(db_session) == before


def test_cleanup_retains_independent_source_records_and_allows_their_next_collection(
    db_session, source, monkeypatch,  # noqa: F811
):
    jobs, _ = legacy_collection(db_session, source, monkeypatch)
    values = {column.name: deepcopy(getattr(source, column.name))
              for column in RecruitmentSource.__table__.columns
              if column.name not in {"id", "created_at", "updated_at"}}
    values.update(original_url=HOST + "/other", url_key="other")
    other = RecruitmentSource(**values)
    db_session.add(other)
    db_session.commit()
    with monkeypatch.context() as legacy:
        legacy.setattr(vacancies, "canonical_vacancy_url", lambda value: value)
        vacancies.ingest_page(db_session, other, page_result([
            posting(identifier=None, url=URL + "?replytocom=3"),
            posting(identifier=None, url=URL + "?replytocom=4"),
        ]), registry.now())
        db_session.commit()
    result = consolidate_duplicate_vacancies(db_session)
    assert result["retired_jobs"] == 4 and result["duplicate_records"] == 3
    records = list(db_session.scalars(select(VacancyRecord).where(
        VacancyRecord.state == "published")))
    assert {record.source_id for record in records} == {source.id, other.id}
    assert all(record.job_id == jobs[0].id for record in records)
    vacancies.ingest_page(db_session, other, page_result([
        posting(identifier=None, url=URL + "?replytocom=5"),
    ]), registry.now() + timedelta(seconds=1))
    db_session.commit()
    assert [job.id for job in list_open_jobs(db_session)] == [jobs[0].id]
    assert db_session.scalar(select(func.count()).select_from(Job)) == 5


def test_saved_alias_follows_retained_detail_reminders_and_old_form_actions(
    db_session, source, staff, client, monkeypatch,  # noqa: F811
):
    now = registry.now()
    jobs, _ = legacy_collection(db_session, source, monkeypatch,
                                deadline=(now + timedelta(hours=24)).isoformat())
    keeper, old = jobs[:2]
    watch.save_job(db_session, staff, old, remind=True)
    created = db_session.get(SavedOpportunity, (staff.id, old.id)).created_at
    result = consolidate_duplicate_vacancies(db_session)
    assert result["saved_opportunities_moved"] == 1
    assert db_session.get(SavedOpportunity, (staff.id, old.id)) is None
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)).created_at == created
    assert watch.generate_alerts(db_session, now=now)["reminders"] == 1
    assert watch.generate_alerts(db_session, now=now)["reminders"] == 0
    notice = db_session.scalar(select(Notification).where(Notification.kind == "deadline_reminder"))
    assert notice.job_id == keeper.id
    as_member(client, staff)
    detail = client.get(f"/jobs/{old.id}")
    assert "Saved to your opportunities" in detail.text
    assert f"/jobs/{keeper.id}/save" not in detail.text
    assert keeper.title in client.get("/jobs/saved").text
    token = csrf_from(client.get("/jobs/saved"))
    response = client.post(f"/jobs/{old.id}/reminder", data={"csrf_token": token})
    assert response.status_code == 200
    assert not db_session.get(SavedOpportunity, (staff.id, keeper.id)).remind
    response = client.post(f"/jobs/{old.id}/unsave", data={"csrf_token": token})
    assert response.status_code == 200
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)) is None
    response = client.post(f"/jobs/{old.id}/save", data={"csrf_token": token, "remind": "true"})
    assert response.status_code == 200
    assert response.url.path == f"/jobs/{keeper.id}"
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)).remind
    # A second account cannot change/remove the owner's canonical bookmark through an old link.
    from app.models.user import User

    peer = User(phone="+2348000000288", hashed_password="unused")
    db_session.add(peer)
    db_session.commit()
    as_member(client, peer)
    token = csrf_from(client.get("/jobs/saved"))
    assert client.post(f"/jobs/{old.id}/reminder", data={"csrf_token": token}).status_code == 404
    client.post(f"/jobs/{old.id}/unsave", data={"csrf_token": token})
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)).remind


def test_consolidation_preserves_sent_and_read_reminders_without_repeating_delivery(
    db_session, source, staff, monkeypatch,  # noqa: F811
):
    from app.services import notifications
    from app.services.notification_worker import run_next

    now = registry.now()
    jobs, _ = legacy_collection(db_session, source, monkeypatch,
                                deadline=(now + timedelta(hours=24)).isoformat())
    keeper, old = jobs[:2]
    for job in [keeper, old]:
        watch.save_job(db_session, staff, job, remind=True)
    assert watch.generate_alerts(db_session, now=now)["reminders"] == 2
    alias_notice = db_session.scalar(select(Notification).where(Notification.job_id == old.id))
    alias_notice.email_state, alias_notice.read_at = "sent", now
    db_session.commit()
    result = consolidate_duplicate_vacancies(db_session)
    assert result["saved_opportunities_merged"] == 1
    canonical = db_session.scalar(select(Notification).where(Notification.job_id == keeper.id))
    assert canonical.email_state == "sent" and registry.utc(canonical.read_at) == now
    assert not db_session.get(Notification, alias_notice.id).in_app
    assert db_session.scalar(select(func.count()).select_from(Notification)) == 2
    assert watch.generate_alerts(db_session, now=now)["reminders"] == 0
    assert run_next(db_session, now=now) is None
    assert notifications.unread_count(db_session, staff) == 0
    assert len(notifications.inbox_page(db_session, staff)[0]) == 1
    assert not any(consolidate_duplicate_vacancies(db_session)[key] for key in [
        "saved_opportunities_moved", "saved_opportunities_merged",
        "notifications_retargeted", "notifications_suppressed",
    ])


def test_existing_alias_history_repair_rolls_back_and_keeps_reminder_opt_out(
    db_session, source, staff, monkeypatch,  # noqa: F811
):
    jobs, _ = legacy_collection(db_session, source, monkeypatch)
    keeper, old = jobs[:2]
    consolidate_duplicate_vacancies(db_session)
    watch.save_job(db_session, staff, keeper, remind=True)
    # Represents member history left by the earlier maintenance implementation.
    db_session.add(SavedOpportunity(user_id=staff.id, job_id=old.id, remind=False))
    db_session.commit()
    preview = consolidate_duplicate_vacancies(db_session, dry_run=True)
    assert preview["groups"] == 0 and preview["saved_opportunities_merged"] == 1
    assert db_session.get(SavedOpportunity, (staff.id, old.id)) is not None
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)).remind
    assert consolidate_duplicate_vacancies(db_session) == preview
    assert db_session.get(SavedOpportunity, (staff.id, old.id)) is None
    assert not db_session.get(SavedOpportunity, (staff.id, keeper.id)).remind
    event = db_session.scalar(select(VacancyEvent).where(
        VacancyEvent.action == "saved_opportunities_reconciled"))
    assert event.details["saved_opportunities_merged"] == 1
    assert str(staff.id) not in str(event.details)


def test_alias_notice_without_canonical_copy_keeps_id_and_event_deduplication(
    db_session, source, staff, monkeypatch,  # noqa: F811
):
    from app.services.notifications import emit, inbox_page

    jobs, _ = legacy_collection(db_session, source, monkeypatch)
    keeper, old = jobs[:2]
    emit(db_session, actor_id=None, recipients={staff.id}, category="opportunities",
         kind="opportunity_match", event_key=f"match:{old.id}", job_id=old.id)
    db_session.commit()
    notice = db_session.scalar(select(Notification))
    identifier = notice.id
    result = consolidate_duplicate_vacancies(db_session)
    assert result["notifications_retargeted"] == 1
    notice = db_session.get(Notification, identifier)
    assert notice.job_id == keeper.id and notice.event_key == f"match:{keeper.id}"
    assert len(inbox_page(db_session, staff)[0]) == 1
    emit(db_session, actor_id=None, recipients={staff.id}, category="opportunities",
         kind="opportunity_match", event_key=f"match:{keeper.id}", job_id=keeper.id)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Notification)) == 1


def test_queued_alias_deadline_survives_consolidation_and_delivers_once_to_file(
    db_session, source, staff, monkeypatch, tmp_path,  # noqa: F811
):
    from app.core.config import settings
    from app.services import notifications
    from app.services.notification_worker import run_next

    monkeypatch.setattr(settings, "account_mail_backend", "file")
    monkeypatch.setattr(settings, "account_mail_dir", str(tmp_path / "mail"))
    now = registry.now()
    staff.email, staff.email_verified_at = "assessment@example.org", now
    db_session.commit()
    choices = notifications.preferences(db_session, staff)
    choices["opportunities"]["email"] = True
    notifications.save_preferences(db_session, staff, choices)
    jobs, _ = legacy_collection(db_session, source, monkeypatch,
                                deadline=(now + timedelta(hours=24)).isoformat())
    keeper, old = jobs[:2]
    watch.save_job(db_session, staff, old, remind=True)
    assert watch.generate_alerts(db_session, now=now)["reminders"] == 1
    notice = db_session.scalar(select(Notification))
    identifier = notice.id
    assert notice.email_state == "queued"
    result = consolidate_duplicate_vacancies(db_session)
    assert result["notifications_retargeted"] == 1
    notice = db_session.get(Notification, identifier)
    assert notice.job_id == keeper.id
    assert notice.event_key == f"deadline:{keeper.id}:{registry.utc(keeper.closes_at).isoformat()}"
    assert watch.generate_alerts(db_session, now=now)["reminders"] == 0
    assert run_next(db_session, now=now + timedelta(seconds=10)) == (identifier, "sent")
    assert run_next(db_session, now=now + timedelta(seconds=10)) is None
    assert len(list((tmp_path / "mail").glob("*.eml"))) == 1


def test_invalid_alias_cannot_move_a_bookmark_to_another_announcement(
    db_session, source, staff, client, monkeypatch,  # noqa: F811
):
    jobs, _ = legacy_collection(db_session, source, monkeypatch)
    keeper, old = jobs[:2]
    consolidate_duplicate_vacancies(db_session)
    # A corrupted alias marker must not bypass announcement matching.
    old.normalized_data = {**old.normalized_data, "announcement_url": URL + "/different"}
    db_session.add(SavedOpportunity(user_id=staff.id, job_id=old.id, remind=False))
    db_session.commit()
    result = consolidate_duplicate_vacancies(db_session)
    assert result["saved_opportunities_moved"] == result["saved_opportunities_merged"] == 0
    assert db_session.get(SavedOpportunity, (staff.id, old.id)) is not None
    assert db_session.get(SavedOpportunity, (staff.id, keeper.id)) is None
    as_member(client, staff)
    token = csrf_from(client.get("/jobs/saved"))
    assert client.get(f"/jobs/{old.id}").status_code == 404
    assert client.post(f"/jobs/{old.id}/save", data={"csrf_token": token}).status_code == 404
