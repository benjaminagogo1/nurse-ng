"""Factual publication through the real queue, assessment and ingestion services."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.jobs import effective_job_status, job_card, list_open_jobs
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancies import collector_authorized
from tests.test_automatic_activation import check, evidence, source  # noqa: F401
from tests.test_recruitment_fetch import ScriptedFetcher

HOME = "https://health.example.gov.ng/"
PAGE = HOME + "announcements/graduate-health-internship"
NAME = "State Health Agency"
PROSE = "Distinctive original paragraphs about programme responsibilities and eligibility."


def fixture(db, *, host=HOME, deadline=None, publication="", records=True):
    deadline = (
        deadline
        if deadline is not None
        else (registry.now() + timedelta(days=21)).date().isoformat()
    )
    item, _ = registry.register_candidate(
        db,
        identity_key="manual:state-health",
        name=NAME,
        category="public_health",
        country_code="NG",
        location="",
        website_url=host,
        source_url=host,
        discovered_via="manual",
        reference=host,
        source_type="institution_site",
    )
    db.commit()
    target = host + "announcements/graduate-health-internship"
    body = (
        f"<main><h1>Graduate Health Internship</h1><p>Applications are invited in Nigeria.</p>"
        f"<p>Location: Abuja, Nigeria</p><p>Application deadline: {deadline}</p>"
        f"<p>Published: {publication}</p><p>{PROSE}</p></main>"
    )
    fetched = ScriptedFetcher(
        {
            host + "sitemap.xml": FetchedPage("", 404, "", b""),
            host + "robots.txt": FetchedPage("", 404, "", b""),
            host: FetchedPage(
                host,
                200,
                "text/html",
                (
                    f"<title>{NAME}</title>"
                    + (f'<a href="{target}">Graduate health internship</a>' if records else "")
                ).encode(),
            ),
            target: FetchedPage(target, 200, "text/html", body.encode()),
        }
    )
    return item, fetched, target


def test_government_announcement_publishes_and_refreshes_without_ror_or_licence(
    db_session, monkeypatch, client
):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session)
    task = check(db_session, item, fetched)
    assert task.status == "completed", task.message
    assert collector_authorized(item), item.activation_review
    assert item.reuse_basis == "factual_index" and item.permission_status == "limited"
    assert not item.allow_snapshot_retention and not item.allow_republication
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.normalized_data["announcement_url"] == target
    assert job.normalized_data["publication_date"] == ""
    assert job_card(job)["date_label"] == "First listed"
    assert effective_job_status(job) == "open"
    assert PROSE not in job.description
    page = client.get(f"/jobs/{job.id}")
    assert page.status_code == 200 and "First listed" in page.text and target in page.text
    for snapshot in db_session.scalars(select(VacancySnapshot)):
        assert PROSE.encode() not in snapshot.body
        assert "<main>" not in snapshot.body.decode()
        assert isinstance(json.loads(snapshot.body)["records"], list)
    for record in db_session.scalars(select(VacancyRecord)):
        assert PROSE not in json.dumps(record.raw_record)
    for event in db_session.scalars(select(VacancyEvent)):
        assert PROSE not in json.dumps(event.details)
    before = job.confirmed_at
    # Due-source expansion may have queued the detail as well; both real paths work.
    for _ in range(2):
        check(db_session, item, fetched)
    db_session.refresh(job)
    assert job.confirmed_at >= before
    assert len(list_open_jobs(db_session)) == 1
    item.verification_status = "revoked"
    db_session.commit()
    assert not collector_authorized(item) and list_open_jobs(db_session) == []


@pytest.mark.parametrize(
    "host",
    [
        "https://health.gov.ng.attacker.org/",
        "https://health-gov.ng/",
        "https://private.example.ng/",
    ],
)
def test_unverified_publishers_do_not_activate(db_session, monkeypatch, host):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, _ = fixture(db_session, host=host)
    check(db_session, item, fetched)
    assert not collector_authorized(item)
    assert list_open_jobs(db_session) == []


@pytest.mark.parametrize("deadline", ["03/04/2028", "2020-01-01"])
def test_ambiguous_or_expired_deadlines_never_appear_as_open(
    db_session, monkeypatch, deadline
):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, _ = fixture(db_session, deadline=deadline)
    check(db_session, item, fetched)
    assert collector_authorized(item)
    assert list_open_jobs(db_session) == []


def test_verified_empty_channel_activates_without_inventing_jobs(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, _ = fixture(db_session, records=False)
    check(db_session, item, fetched)
    assert collector_authorized(item)
    assert list_open_jobs(db_session) == []


def test_directory_source_without_cc_licence_indexes_facts(db_session, source):  # noqa: F811
    fetched = evidence(licence="")
    task = check(db_session, source, fetched)
    assert task.status == "completed", task.message
    assert source.collection_adapter == "factual_index"
    assert len(list_open_jobs(db_session)) == 1
    assert not source.allow_republication


def test_programme_activates_from_live_government_backlink(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, _ = fixture(db_session, host="https://fellowship.example.ng/")
    from app.models.recruitment import SourceEvent

    reference = HOME + "programmes"
    discovered = db_session.scalar(select(SourceEvent).where(SourceEvent.source_id == item.id))
    discovered.reference_url = reference
    db_session.commit()
    fetched.responses[HOME + "robots.txt"] = FetchedPage("", 404, "", b"")
    fetched.responses[reference] = FetchedPage(
        reference,
        200,
        "text/html",
        ('<a href="https://fellowship.example.ng/">Official programme</a>').encode(),
    )
    check(db_session, item, fetched)
    assert collector_authorized(item), item.activation_review
    assert item.activation_review["evidence"]["identity_basis"] == "authoritative_backlink"
    assert len(list_open_jobs(db_session)) == 1
    fetched.responses[reference] = FetchedPage(reference, 200, "text/html", b"Link withdrawn")
    check(db_session, item, fetched)
    assert not collector_authorized(item) and list_open_jobs(db_session) == []


def test_failed_detail_hides_only_that_detail(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session)
    check(db_session, item, fetched)
    assert len(list_open_jobs(db_session)) == 1
    fetched.responses[target] = FetchedPage(target, 503, "text/html", b"Unavailable")
    task = check(db_session, item, fetched)
    assert task.status == "completed"
    assert collector_authorized(item)
    assert list_open_jobs(db_session) == []


def test_search_schedule_is_created_once_and_pause_is_preserved(db_session, monkeypatch):
    from app.core.config import settings
    from app.models.recruitment import DiscoverySchedule

    monkeypatch.setattr(settings, "recruitment_search_key", "")
    monkeypatch.setattr(settings, "recruitment_search_permission_reference", "")
    assert registry.ensure_search_schedule(db_session) == 0
    monkeypatch.setattr(settings, "recruitment_search_key", "isolated-test-key")
    monkeypatch.setattr(
        settings, "recruitment_search_permission_reference", "https://example.org/terms"
    )
    assert registry.ensure_search_schedule(db_session) == 1
    schedule = db_session.scalar(select(DiscoverySchedule))
    assert schedule.provider == "search" and schedule.country_code == "NG"
    assert schedule.interval_hours == 6
    schedule.enabled = False
    db_session.commit()
    assert registry.ensure_search_schedule(db_session) == 0
    assert not schedule.enabled


@pytest.mark.parametrize('title', ['Graduate Health Internship', 'Pharmacist', 'Dental Assistant'])
def test_missing_deadline_keeps_listing_without_claiming_applications_are_open(
    db_session, monkeypatch, title,
):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session, deadline="")
    fetched.responses[HOME].body = fetched.responses[HOME].body.replace(
        b'Graduate health internship', title.encode(),
    )
    fetched.responses[target].body = fetched.responses[target].body.replace(
        b'Graduate Health Internship', title.encode(),
    )
    fetched.responses[HOME].body += b"<h2>Current vacancies</h2>"
    fetched.responses[target].body += (
        b'<form action="/jobs/apply" method="post"><input name="job_id" value="42">'
        b"<button>Apply</button></form>"
    )
    check(db_session, item, fetched)
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1, [
        (r.normalized, r.issues) for r in db_session.scalars(select(VacancyRecord))
    ]
    assert jobs[0].closes_at is None
    assert jobs[0].title == title
    assert jobs[0].normalized_data["_index"]["accepting_applications"]
    assert jobs[0].normalized_data["closing_date"] == ""
    fetched.responses[target].body = fetched.responses[target].body.replace(
        b'name="job_id"', b'name="irrelevant"'
    )
    check(db_session, item, fetched)
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1
    assert not jobs[0].normalized_data['_index']['accepting_applications']
    assert job_card(jobs[0])['status_label'] == 'Check availability'


def test_unresolved_deadline_not_overridden_by_application_form(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session, deadline="03/04/2028")
    fetched.responses[HOME].body += b"<h2>Current vacancies</h2>"
    fetched.responses[
        target
    ].body += b'<form action="/jobs/apply" method="post"><input name="job_id" value="42"></form>'
    check(db_session, item, fetched)
    assert list_open_jobs(db_session) == []


def test_original_changes_are_tracked_without_retaining_original_body(db_session, monkeypatch):
    import hashlib

    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, _ = fixture(db_session)
    check(db_session, item, fetched)
    original_hash = item.content_hash
    fetched.responses[HOME].body += b"<p>Publisher notice changed.</p>"
    check(db_session, item, fetched)
    assert item.content_hash != original_hash
    assert item.content_hash == hashlib.sha256(fetched.responses[HOME].body).hexdigest()
    assert all(
        b"Publisher notice changed" not in row.body
        for row in db_session.scalars(select(VacancySnapshot))
    )
