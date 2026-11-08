"""Automatic activation uses real adapter/worker paths with isolated evidence fixtures."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.jobs import Job
from app.models.recruitment import SourceEvent
from app.models.user import User
from app.models.vacancies import VacancyRecord, VacancySnapshot
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.jobs import effective_job_status, list_open_jobs
from app.services.recruitment_discovery import execute_discovery
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancies import collector_authorized, configure_collector
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_recruitment import approve
from tests.test_recruitment_fetch import ScriptedFetcher
from tests.test_vacancy_ingestion import posting

SITE = "https://hospital.example.ng"
PAGE = SITE + "/recruitment"
IDENTITY = "https://ror.org/012345678"
DIRECTORY = "https://api.ror.org/v2/organizations/012345678"
LICENCE = "https://creativecommons.org/licenses/by/4.0/"


@pytest.fixture
def source(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, _ = registry.register_candidate(
        db_session, identity_key=IDENTITY, name="Example Hospital", category="healthcare",
        country_code="NG", location="Lagos", website_url=SITE, source_url=PAGE,
        discovered_via="ror", reference=IDENTITY, source_type="recruitment_page",
    )
    db_session.commit()
    return item


def evidence(*, licence=LICENCE, home_link=PAGE, country="NG", records=None, directory=None):
    raw = records if records is not None else [posting(url=PAGE + "/nurse-123")]
    body = ("<html><head><title>Nursing recruitment</title>"
            + (f'<link rel="license" href="{licence}">' if licence else "")
            + '</head><body><script type="application/ld+json">'
            + json.dumps(raw).replace("<", "\\u003c") + "</script></body></html>")
    data = {
        "id": IDENTITY, "status": "active", "types": ["healthcare"],
        "names": [{"value": "Example Hospital"}],
        "links": [{"type": "website", "value": SITE}],
        "locations": [{"geonames_details": {"country_code": country}}],
        **(directory or {}),
    }
    return ScriptedFetcher({
        PAGE: FetchedPage(PAGE, 200, "text/html", body.encode()),
        SITE: FetchedPage(SITE, 200, "text/html", (
            f'<html><title>Example Hospital</title><a href="{home_link}">Recruitment</a></html>'
        ).encode()),
        SITE + "/robots.txt": FetchedPage(SITE + "/robots.txt", 404, "", b""),
        DIRECTORY: FetchedPage(DIRECTORY, 200, "application/json", json.dumps(data).encode()),
    })


def check(db, source, fetcher):
    source.next_check_at = registry.now() - timedelta(seconds=1)
    db.commit()
    worker.enqueue_due(db)
    task = worker.run_next(db, executor=lambda kind, payload: execute_discovery(
        kind, payload, fetcher=fetcher,
    ))
    db.expire_all()
    return task


def staff(db):
    actor = User(phone="+2348012345678", hashed_password="unused", is_staff=True)
    db.add(actor)
    db.commit()
    return actor


@pytest.mark.parametrize("licence", [LICENCE, "https://creativecommons.org/publicdomain/zero/1.0/"])
def test_passing_source_activates_and_publishes_without_staff(db_session, source, client, licence):
    fetched = evidence(licence=licence)
    task = check(db_session, source, fetched)
    assert task.status == "completed", task.message
    assert source.verification_status == "approved"
    assert source.approval_mode == "automatic" and collector_authorized(source)
    assert source.deadline_timezone == "Africa/Lagos"
    assert source.reuse_url_prefix == source.vacancy_url_prefix == PAGE
    assert source.original_url == PAGE
    assert source.activation_review["evidence"]["directory"] == DIRECTORY
    assert db_session.scalar(select(func.count()).select_from(User)) == 0
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1
    snapshot = db_session.scalar(select(VacancySnapshot))
    assert snapshot.body == fetched.responses[PAGE].body
    event = db_session.scalar(select(SourceEvent).where(SourceEvent.kind == "automatic_activation"))
    assert event.actor_id is None and event.task_id == task.id
    detail = client.get(f"/jobs/{jobs[0].id}")
    assert detail.status_code == 200 and licence in detail.text
    assert "Adapted from" in detail.text
    assert all(url.startswith("https://") for url, _ in fetched.calls)


@pytest.mark.parametrize("kwargs,reason", [
    ({"licence": ""}, "reuse terms"),
    ({"licence": "https://creativecommons.org/licenses/by-nc/4.0/"}, "reuse terms"),
    ({"home_link": SITE + "/other"}, "direct link"),
    ({"directory": {"status": "inactive"}}, "directory record"),
    ({"directory": {"links": [{"type": "website", "value": "https://other.example.org"}]}},
     "directory record"),
    ({"directory": {"names": [{"value": "Different Hospital"}]}}, "directory record"),
    ({"country": "GB"}, "directory record"),
    ({"records": []}, "No relevant structured opportunity"),
    ({"records": [posting(hiringOrganization={"name": "Other employer"})]},
     "No relevant structured opportunity"),
])
def test_uncertain_sources_get_actionable_review_reasons(db_session, source, kwargs, reason):
    task = check(db_session, source, evidence(**kwargs))
    assert task.status == "completed", task.message
    assert source.verification_status == "pending" and not collector_authorized(source)
    assert any(reason in value for value in source.activation_review["reasons"])
    assert "needs review" in task.message
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 0
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize("title,job_type", [
    ("National Health Fellow", "fellowship"),
    ("Nigeria Jubilee Fellows Programme", "fellowship"),
    ("Digital Health Internship", "internship"),
    ("Graduate Trainee Programme", "graduate_programme"),
])
def test_worker_publishes_eligible_programmes_and_keeps_source_requirements(
    db_session, source, title, job_type,
):
    raw = posting(
        title=title, url=PAGE + "/programme", description="Supervised placement and training.",
        qualifications="See the programme's degree, age and residence requirements.",
    )
    task = check(db_session, source, evidence(records=[raw]))
    assert task.status == "completed"
    assert source.approval_mode == "automatic" and collector_authorized(source)
    jobs = list_open_jobs(db_session, job_type=job_type)
    assert len(jobs) == 1 and jobs[0].title == title
    assert jobs[0].normalized_data["qualifications"] == raw["qualifications"]
    assert jobs[0].normalized_data["employment_type_text"] == "FULL_TIME"


def test_manual_candidate_is_not_treated_as_directory_verified(db_session, source):
    source.organization.identity_key = "manual:unverified"
    fetched = evidence()
    check(db_session, source, fetched)
    assert "independent organisation" in source.activation_review["reasons"][0]
    assert DIRECTORY not in [url for url, _ in fetched.calls]
    assert list_open_jobs(db_session) == []


def test_reversed_salary_goes_to_vacancy_review_without_blocking_source(db_session, source):
    raw = posting(url=PAGE + "/nurse", baseSalary={"currency": "NGN", "value": {
        "unitText": "MONTH", "minValue": 100000, "maxValue": 10000,
    }})
    check(db_session, source, evidence(records=[raw]))
    assert collector_authorized(source) and source.approval_mode == "automatic"
    assert list_open_jobs(db_session) == []
    record = db_session.scalar(select(VacancyRecord))
    assert record.state == "pending" and any(issue.startswith("salary:") for issue in record.issues)
    assert record.raw_record == raw
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 1


def test_changed_terms_disable_then_restore_automatic_collection(db_session, source):
    check(db_session, source, evidence())
    job_id = list_open_jobs(db_session)[0].id
    first_expiry = source.approval_expires_at
    check(db_session, source, evidence())
    assert source.approval_expires_at > first_expiry
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 1
    check(db_session, source, evidence(licence=""))
    assert source.verification_status == "pending" and not collector_authorized(source)
    assert list_open_jobs(db_session) == []
    assert effective_job_status(db_session.get(Job, job_id)) == "unconfirmed"
    check(db_session, source, evidence())
    assert [job.id for job in list_open_jobs(db_session)] == [job_id]


def test_automatic_approval_expires_without_a_worker(db_session, source):
    check(db_session, source, evidence())
    source.approval_expires_at = registry.now() - timedelta(seconds=1)
    db_session.commit()
    assert not collector_authorized(source) and list_open_jobs(db_session) == []
    check(db_session, source, evidence())
    assert collector_authorized(source) and len(list_open_jobs(db_session)) == 1


@pytest.mark.parametrize("action", ["pause", "revoke", "reject", "reopen", "approve"])
def test_staff_decision_during_check_fences_automatic_activation(db_session, source, action):
    actor = staff(db_session)
    worker.enqueue_due(db_session)

    def execute(kind, payload):
        result = execute_discovery(kind, payload, fetcher=evidence())
        if action == "approve":
            approve(db_session, actor, source)
        else:
            registry.review_source(db_session, actor, source, revision=source.revision,
                                   action=action, note="Staff decision during network check")
        return result

    task = worker.run_next(db_session, executor=execute)
    assert task.status == "cancelled"
    assert source.approval_mode != "automatic"
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 0
    assert not source.activation_review


def test_staff_can_hold_or_explicitly_return_source_to_automatic_checks(db_session, source):
    actor = staff(db_session)
    registry.review_source(db_session, actor, source, revision=source.revision,
                           action="reopen", note="Investigate source")
    check(db_session, source, evidence())
    assert source.approval_mode == "staff" and source.verification_status == "pending"
    registry.review_source(db_session, actor, source, revision=source.revision,
                           action="automatic", note="Return to evidence checks")
    check(db_session, source, evidence())
    assert collector_authorized(source) and source.approval_mode == "automatic"
    configure_collector(db_session, actor, source, revision=source.revision, enabled=False,
                        url_prefix="", timezone="", note="Disable collector", reference=PAGE)
    check(db_session, source, evidence())
    assert source.collection_adapter == "" and source.approval_mode == "staff"


def test_network_failure_hides_automatic_jobs_and_retains_originals(db_session, source):
    check(db_session, source, evidence())
    fetched = evidence()
    fetched.responses[PAGE] = FetchedPage(PAGE, 503, "text/html", b"Unavailable")
    task = check(db_session, source, fetched)
    assert task.outcome == "http_error" and source.verification_status == "pending"
    assert list_open_jobs(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 1


def test_country_with_multiple_zones_needs_offset_dates(db_session, source):
    source.organization.country_code = "US"
    raw = posting(url=PAGE + "/nurse", jobLocation={"address": {"addressCountry": "US"}})
    check(db_session, source, evidence(country="US", records=[raw]))
    assert "timezone" in source.activation_review["reasons"][0]
    raw["datePosted"] = (registry.now() - timedelta(days=1)).isoformat()
    raw["validThrough"] = (registry.now() + timedelta(days=20)).isoformat()
    check(db_session, source, evidence(country="US", records=[raw]))
    assert source.deadline_timezone == "UTC" and collector_authorized(source)


def test_mixed_country_date_only_deadlines_require_review(db_session, source):
    records = [posting(url=PAGE + "/nurse-ng"), posting(
        identifier="us-role", url=PAGE + "/nurse-us",
        jobLocation={"address": {"addressCountry": "US"}},
    )]
    check(db_session, source, evidence(records=records))
    assert not collector_authorized(source)
    assert "different countries" in source.activation_review["reasons"][0]


def test_conflicting_canonical_address_requires_review(db_session, source):
    fetched = evidence()
    fetched.responses[PAGE].body = fetched.responses[PAGE].body.replace(
        b"</head>", b'<link rel="canonical" href="https://other.example.org/jobs"></head>',
    )
    check(db_session, source, fetched)
    assert "canonical" in source.activation_review["reasons"][0]
    assert not collector_authorized(source)


def test_automatic_review_ui_is_staff_only_and_reassessment_requires_csrf(
    db_session, source, client,
):
    check(db_session, source, evidence(licence=""))
    response = client.get(f"/recruitment/sources/{source.id}", follow_redirects=False)
    assert response.status_code == 303
    register_and_sign_in(client)
    actor = db_session.scalar(select(User))
    actor.is_staff = True
    db_session.commit()
    page = client.get(f"/recruitment/sources/{source.id}")
    assert "Needs review" in page.text
    assert "No unambiguous supported page-level reuse terms" in page.text
    assert page.headers["Cache-Control"] == "no-store"
    target = f"/recruitment/sources/{source.id}/review"
    values = {"revision": source.revision, "action": "automatic", "note": "Try automatic checks"}
    assert client.post(target, data=values).status_code == 400
    response = client.post(target, data={**values, "csrf_token": csrf_from(page)},
                           follow_redirects=False)
    assert response.status_code == 303
    assert db_session.scalar(select(func.count()).select_from(VacancyRecord)) == 0
