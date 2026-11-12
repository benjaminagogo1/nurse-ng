"""Automatic publication, evidence review and vacancy lifecycle across the shared job UI."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.jobs import Job, JobApplication
from app.models.user import User
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.jobs import (
    JobError,
    apply_for_job,
    effective_job_status,
    job_card,
    list_open_jobs,
)
from app.services.recruitment_discovery import execute_discovery
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancies import configure_collector, review_record
from app.services.vacancy_extraction import extract_records, in_scope, normalize, parse_date
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_recruitment import approve, manual


@pytest.fixture
def staff(db_session):
    user = User(phone="+2348012345678", hashed_password="unused", is_staff=True)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(autouse=True)
def no_cooldown(monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)


@pytest.fixture
def source(db_session, staff):
    item = manual(
        db_session,
        staff,
        name="Example Hospital",
        source_url="https://hospital.example.ng/recruitment",
        website_url="https://hospital.example.ng",
    )
    approve(db_session, staff, item)
    configure_collector(
        db_session,
        staff,
        item,
        revision=item.revision,
        enabled=True,
        url_prefix="https://hospital.example.ng",
        timezone="Africa/Lagos",
        note="Permission includes original snapshots and normalized vacancy republication",
        reference="https://hospital.example.ng/terms",
    )
    return item


def posting(**changes):
    return {
        "@type": "JobPosting",
        "identifier": {"value": "nurse-123"},
        "title": "Registered Nurse",
        "hiringOrganization": {"name": "Example Hospital"},
        "description": "<p>Nursing care in a multidisciplinary team.</p><script>bad()</script>",
        "jobLocation": {
            "address": {
                "addressCountry": "NG",
                "addressRegion": "Lagos",
                "addressLocality": "Ikeja",
            }
        },
        "datePosted": (registry.now() - timedelta(days=3)).date().isoformat(),
        "validThrough": (registry.now() + timedelta(days=30)).date().isoformat(),
        "url": "https://hospital.example.ng/jobs/nurse-123",
        "employmentType": "FULL_TIME",
        "qualifications": "Registered nurse. NMCN registration required.",
        **changes,
    }


def page_result(records):
    body = (
        '<html><script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@graph": records}).replace("<", "\\u003c")
        + "</script></html>"
    ).encode()
    return {
        "ok": True,
        "outcome": "vacancies_collected",
        "observed_url": "https://hospital.example.ng/recruitment",
        "content_hash": hashlib.sha256(body).hexdigest(),
        "body_base64": base64.b64encode(body).decode(),
    }


def collect(db, source, records):
    source.next_check_at = registry.now() - timedelta(seconds=1)
    db.commit()
    worker.enqueue_due(db)
    task = worker.run_next(db, executor=lambda *_: page_result(records))
    db.expire_all()
    assert task.status == "completed", task.message
    return task


def record(db):
    return db.scalar(select(VacancyRecord))


def test_approved_source_publishes_without_per_vacancy_approval_and_preserves_original(
    db_session, source
):
    raw = posting()
    task = collect(db_session, source, [raw])
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1 and jobs[0].employer_user_id is None
    assert jobs[0].source_id == source.id
    assert "1 publishable" in task.message
    assert record(db_session).state == "published"
    snapshot = db_session.scalar(select(VacancySnapshot))
    assert snapshot.body == base64.b64decode(page_result([raw])["body_base64"])
    assert record(db_session).raw_record == raw
    assert "<script>" not in jobs[0].description
    assert jobs[0].normalized_data["application_url"] == ""
    assert jobs[0].normalized_data["opening_date"] == ""
    assert jobs[0].work_mode == ""
    assert jobs[0].salary_min is None
    assert job_card(jobs[0])["salary"] == "Salary not stated"
    assert db_session.scalar(select(func.count()).select_from(VacancyEvent)) == 1


def test_rediscovery_is_idempotent_and_changed_deadline_keeps_history(db_session, source):
    collect(db_session, source, [posting()])
    job_id = record(db_session).job_id
    collect(db_session, source, [posting()])
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    closing = (registry.now() + timedelta(days=2)).date().isoformat()
    collect(db_session, source, [posting(validThrough=closing)])
    assert record(db_session).job_id == job_id
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 2
    assert db_session.scalar(select(func.count()).select_from(VacancyEvent)) == 2
    assert effective_job_status(db_session.get(Job, job_id)) == "closing_soon"


@pytest.mark.parametrize(
    "changes,issue",
    [
        ({"validThrough": ""}, "closing_date"),
        ({"validThrough": "next month"}, "closing_date"),
        ({"validThrough": "2028-01-01T17:00:00"}, "closing_date"),
        ({"hiringOrganization": {"name": "Different company"}}, "employer"),
        ({"jobLocation": {}}, "country"),
        ({"title": "Finance manager"}, "nursing"),
        ({"url": "https://impersonator.example.org/jobs/123"}, "announcement_url"),
        ({"url": "http://127.0.0.1/secret"}, "announcement_url"),
        ({"datePosted": ""}, "publication_date"),
    ],
)
def test_ambiguous_or_unsafe_records_are_held_without_fabrication(
    db_session, source, changes, issue
):
    raw = posting(**changes)
    collect(db_session, source, [raw])
    assert list_open_jobs(db_session) == []
    assert record(db_session).state == "pending"
    assert any(item.startswith(issue + ":") for item in record(db_session).issues)
    assert record(db_session).raw_record == raw


@pytest.mark.parametrize("action", ["revoke", "pause", "reopen"])
def test_permission_change_during_collection_cancels_publication(db_session, source, staff, action):
    worker.enqueue_due(db_session)

    def execute(*_):
        registry.review_source(
            db_session,
            staff,
            source,
            revision=source.revision,
            action=action,
            note="Trust decision changed",
        )
        return page_result([posting()])

    task = worker.run_next(db_session, executor=execute)
    assert task.status == "cancelled"
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 0


def test_expiry_and_freshness_are_enforced_on_reads_even_without_worker(
    db_session, source, monkeypatch
):
    collect(db_session, source, [posting()])
    job = db_session.scalar(select(Job))
    job.confirmed_at = registry.now() - timedelta(hours=49)
    db_session.commit()
    assert list_open_jobs(db_session) == []
    assert effective_job_status(job) == "unconfirmed"
    job.confirmed_at = registry.now()
    source.approval_expires_at = registry.now() - timedelta(seconds=1)
    db_session.commit()
    assert list_open_jobs(db_session) == []


def test_empty_page_and_transient_failure_stop_claiming_open_then_recover(db_session, source):
    collect(db_session, source, [posting()])
    job_id = record(db_session).job_id
    collect(db_session, source, [])
    assert list_open_jobs(db_session) == []
    assert record(db_session).state == "unconfirmed"
    collect(db_session, source, [posting()])
    assert record(db_session).job_id == job_id and len(list_open_jobs(db_session)) == 1
    source.next_check_at = registry.now()
    db_session.commit()
    worker.enqueue_due(db_session)
    worker.run_next(
        db_session, executor=lambda *_: {"ok": False, "outcome": "timeout", "retryable": False}
    )
    db_session.expire_all()
    assert list_open_jobs(db_session) == []
    assert effective_job_status(db_session.get(Job, job_id)) == "unconfirmed"
    assert source.verification_status == "approved"


def test_closed_and_upcoming_vacancies_do_not_claim_current_open_status(db_session, source, staff):
    collect(
        db_session,
        source,
        [posting(validThrough=(registry.now() - timedelta(days=1)).date().isoformat())],
    )
    assert list_open_jobs(db_session) == []
    assert effective_job_status(db_session.scalar(select(Job))) == "closed"
    collect(db_session, source, [posting()])
    item = record(db_session)
    review_record(
        db_session,
        staff,
        item,
        revision=item.revision,
        action="publish",
        note="Official announcement gives a later application opening date",
        reference="https://hospital.example.ng/jobs/nurse-123",
        changes={"opening_date": (registry.now() + timedelta(days=3)).date().isoformat()},
    )
    assert effective_job_status(db_session.scalar(select(Job))) == "upcoming"


def test_staff_corrections_keep_raw_evidence_and_expire_when_source_changes(
    db_session, source, staff
):
    raw = posting(validThrough="")
    collect(db_session, source, [raw])
    item = record(db_session)
    review_record(
        db_session,
        staff,
        item,
        revision=item.revision,
        action="publish",
        note="Deadline clarified by linked announcement",
        reference="https://hospital.example.ng/notice",
        changes={"closing_date": (registry.now() + timedelta(days=15)).date().isoformat()},
    )
    assert len(list_open_jobs(db_session)) == 1
    assert item.raw_record["validThrough"] == ""
    assert item.normalized["_review"]["changes"]["closing_date"]
    collect(db_session, source, [raw])
    assert len(list_open_jobs(db_session)) == 1
    collect(
        db_session,
        source,
        [posting(validThrough="", description="Updated eligibility requirements")],
    )
    assert list_open_jobs(db_session) == []
    assert "_review" not in record(db_session).normalized


def test_rejected_record_is_not_republished_and_stale_reviews_are_rejected(
    db_session, source, staff
):
    collect(db_session, source, [posting()])
    item = record(db_session)
    old = item.revision
    review_record(
        db_session,
        staff,
        item,
        revision=old,
        action="reject",
        note="Suspected impersonation",
        reference="https://hospital.example.ng/notice",
    )
    with pytest.raises(registry.RecruitmentError, match="changed"):
        review_record(
            db_session,
            staff,
            item,
            revision=old,
            action="publish",
            note="Old form",
            reference="https://hospital.example.ng/notice",
        )
    db_session.rollback()
    collect(db_session, source, [posting()])
    assert record(db_session).state == "rejected" and list_open_jobs(db_session) == []


def test_international_salary_country_and_original_application_display(db_session, source, client):
    raw = posting(
        jobLocation={"address": {"addressCountry": "NZ", "addressLocality": "Auckland"}},
        baseSalary={
            "currency": "NZD",
            "value": {"minValue": 70000, "maxValue": 85000, "unitText": "YEAR"},
        },
    )
    collect(db_session, source, [raw])
    job = db_session.scalar(select(Job))
    assert job_card(job)["salary"] == "NZD 70,000 – 85,000 per year"
    assert len(list_open_jobs(db_session, country_code="NZ")) == 1
    assert list_open_jobs(db_session, country_code="NG") == []
    detail = client.get(f"/jobs/{job.id}")
    assert detail.status_code == 200
    assert "External application" in detail.text and "Open original vacancy" in detail.text
    assert "Sign in to apply" not in detail.text and 'action="/jobs/' not in detail.text
    assert "Approved recruitment source" in client.get("/jobs?country=NZ").text
    assert "Registered Nurse" not in client.get("/jobs?country=NG").text


@pytest.mark.parametrize(
    "values",
    [
        {"minValue": 100000, "maxValue": 10000},
        {"minValue": "10.50", "maxValue": "10.49", "value": "10.50"},
    ],
)
def test_reversed_salary_range_is_held_with_original_evidence(db_session, source, staff, values):
    raw = posting(baseSalary={"currency": "NGN", "value": {"unitText": "MONTH", **values}})
    collect(db_session, source, [raw])
    item = record(db_session)
    assert list_open_jobs(db_session) == []
    assert item.state == "pending"
    assert any(issue.startswith("salary:") for issue in item.issues)
    assert item.raw_record == raw
    snapshot = db_session.get(VacancySnapshot, item.snapshot_id)
    assert snapshot.body == base64.b64decode(page_result([raw])["body_base64"])

    with pytest.raises(registry.RecruitmentError, match="salary:"):
        review_record(
            db_session,
            staff,
            item,
            revision=item.revision,
            action="publish",
            note="Attempt to publish without correcting the salary contradiction",
            reference=raw["url"],
        )
    db_session.rollback()
    assert list_open_jobs(db_session) == []


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"minValue": "9.50", "maxValue": "10.00"}, "NGN 9.50 – 10.00 per month"),
        ({"minValue": 0, "maxValue": 0}, "NGN 0 – 0 per month"),
        ({"minValue": 10000}, "NGN from 10,000 per month"),
        ({"maxValue": 100000}, "NGN up to 100,000 per month"),
        ({"value": 50000}, "NGN 50,000 per month"),
    ],
)
def test_valid_salary_amounts_still_publish(db_session, source, values, expected):
    collect(db_session, source, [posting(baseSalary={
        "currency": "NGN", "value": {"unitText": "MONTH", **values},
    })])
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1
    assert job_card(jobs[0])["salary"] == expected


def test_salary_range_regression_hides_job_until_source_corrects_it(db_session, source):
    valid = posting(baseSalary={
        "currency": "NGN",
        "value": {"unitText": "MONTH", "minValue": 10000, "maxValue": 100000},
    })
    collect(db_session, source, [valid])
    job_id = record(db_session).job_id

    collect(db_session, source, [posting(baseSalary={
        "currency": "NGN",
        "value": {"unitText": "MONTH", "minValue": 100000, "maxValue": 10000},
    })])
    assert list_open_jobs(db_session) == []
    assert record(db_session).state == "pending"
    assert effective_job_status(db_session.get(Job, job_id)) == "unconfirmed"

    collect(db_session, source, [valid])
    assert [job.id for job in list_open_jobs(db_session)] == [job_id]
    assert record(db_session).state == "published"
    assert record(db_session).issues == []


def test_platform_application_cannot_collect_contacts_for_external_job(db_session, source, staff):
    collect(db_session, source, [posting()])
    with pytest.raises(JobError, match="original announcement"):
        apply_for_job(db_session, staff, db_session.scalar(select(Job)), cover_note="hello")
    assert db_session.scalar(select(func.count()).select_from(JobApplication)) == 0


def test_exact_url_duplicates_merge_but_conflicts_hold_public_job(db_session, source, staff):
    collect(db_session, source, [posting()])
    first_id = record(db_session).job_id
    other = manual(
        db_session,
        staff,
        name="Second approved channel",
        source_url="https://hospital.example.ng/other",
        website_url="https://hospital.example.ng",
    )
    approve(db_session, staff, other)
    configure_collector(
        db_session,
        staff,
        other,
        revision=other.revision,
        enabled=True,
        url_prefix="https://hospital.example.ng",
        timezone="Africa/Lagos",
        note="Licensed channel",
        reference="https://hospital.example.ng/terms",
    )
    # Same employer has a second approved channel. Correct its organization name, then reapprove.
    other.organization.name = "Example Hospital"
    db_session.commit()
    collect(db_session, other, [posting()])
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert all(item.job_id == first_id for item in db_session.scalars(select(VacancyRecord)))
    collect(
        db_session,
        other,
        [posting(validThrough=(registry.now() + timedelta(days=10)).date().isoformat())],
    )
    assert list_open_jobs(db_session) == []
    assert any(
        "conflict:" in issue
        for item in db_session.scalars(select(VacancyRecord))
        for issue in item.issues
    )


def test_configuration_requires_approval_and_respects_current_revision(db_session, staff):
    source = manual(db_session, staff)
    with pytest.raises(registry.RecruitmentError, match="Approve"):
        configure_collector(
            db_session,
            staff,
            source,
            revision=source.revision,
            enabled=True,
            url_prefix="https://lshsc.ng",
            timezone="Africa/Lagos",
            note="Set up",
            reference="https://lshsc.ng/terms",
        )
    assert source.collection_adapter == ""


def test_parser_does_not_execute_scripts_or_treat_generic_guidance_as_a_job():
    assert (
        extract_records(b'<script>alert("JobPosting")</script><p>Recruitment information</p>') == []
    )
    raw = posting()
    data = normalize(
        raw
        | {
            "jobStartDate": "2028-01-01",
            "occupationalCredentialAwarded": "Not a licence requirement",
        }
    )
    assert data["opening_date"] == "" and data["registration_requirements"] == ""
    assert "bad()" not in data["description"]
    assert not in_scope(
        "https://hospital.example.ng/jobs/%2e%2e/secret", "https://hospital.example.ng/jobs"
    )
    assert not in_scope(
        "https://hospital.example.ng/jobs-elsewhere", "https://hospital.example.ng/jobs"
    )


def test_date_only_deadline_uses_inclusive_local_day_without_inventing_utc_time():
    assert parse_date("2027-01-05", "Africa/Lagos", closing=True) == datetime(
        2027, 1, 5, 23, tzinfo=UTC
    )
    assert parse_date("2027-01-05T17:00:00", "Africa/Lagos", closing=True) is None
    assert parse_date("2027-01-05T17:00:00+01:00", "Africa/Lagos", closing=True) == datetime(
        2027, 1, 5, 16, tzinfo=UTC
    )


def test_actual_adapter_result_flows_through_worker(db_session, source):
    body = base64.b64decode(page_result([posting()])["body_base64"])

    class Fetcher:
        def get(self, url, **kwargs):
            assert kwargs["allowed_origin"] == "https://hospital.example.ng"
            return FetchedPage(url, 200, "text/html", body)

    worker.enqueue_due(db_session)
    task = worker.run_next(
        db_session,
        executor=lambda kind, payload: execute_discovery(kind, payload, fetcher=Fetcher()),
    )
    assert task.status == "completed" and len(list_open_jobs(db_session)) == 1


def test_raw_snapshot_and_review_routes_require_staff_and_csrf(client, db_session, source):
    collect(db_session, source, [posting(validThrough="")])
    item = record(db_session)
    path = f"/recruitment/vacancies/{item.id}"
    assert client.get(path + "/original", follow_redirects=False).status_code == 303
    register_and_sign_in(client, phone="+2348099999999")
    assert client.get(path).status_code == 403
    user = db_session.scalar(select(User).where(User.phone == "+2348099999999"))
    user.is_staff = True
    db_session.commit()
    page = client.get(path)
    assert page.status_code == 200
    download = client.get(path + "/original")
    assert download.status_code == 200 and download.headers["X-Content-Type-Options"] == "nosniff"
    assert download.headers["Content-Disposition"].startswith("attachment")
    assert client.post(path + "/review", data={"revision": item.revision}).status_code == 400
    result = client.post(
        path + "/review",
        data={
            "csrf_token": csrf_from(page),
            "revision": item.revision,
            "action": "publish",
            "note": "Official clarification",
            "reference": "https://hospital.example.ng/notice",
            "closing_date": (registry.now() + timedelta(days=10)).date().isoformat(),
        },
    )
    assert result.status_code == 200, result.text
    assert len(list_open_jobs(db_session)) == 1


def test_invalid_structured_page_is_recorded_as_failure_and_hides_previous_job(db_session, source):
    collect(db_session, source, [posting()])
    source.next_check_at = registry.now()
    db_session.commit()
    worker.enqueue_due(db_session)
    body = b'<script type="application/ld+json">{"broken":</script>'
    result = {
        "ok": True,
        "outcome": "vacancies_collected",
        "observed_url": source.original_url,
        "content_hash": hashlib.sha256(body).hexdigest(),
        "body_base64": base64.b64encode(body).decode(),
    }
    task = worker.run_next(db_session, executor=lambda *_: result)
    db_session.expire_all()
    assert task.status == "failed"
    assert list_open_jobs(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 2
    assert source.health_status == "extraction_error"


def test_review_error_preserves_corrections_and_cannot_bypass_url_scope(client, db_session, source):
    collect(db_session, source, [posting(validThrough="")])
    register_and_sign_in(client, phone="+2348077777777")
    user = db_session.scalar(select(User).where(User.phone == "+2348077777777"))
    user.is_staff = True
    db_session.commit()
    item = record(db_session)
    path = f"/recruitment/vacancies/{item.id}"
    page = client.get(path)
    result = client.post(
        path + "/review",
        data={
            "csrf_token": csrf_from(page),
            "revision": item.revision,
            "action": "publish",
            "note": "Keep this evidence note",
            "reference": "https://hospital.example.ng/notice",
            "title": "Nurse specialist",
            "announcement_url": "https://elsewhere.example.org",
            "closing_date": (registry.now() + timedelta(days=10)).date().isoformat(),
        },
    )
    assert result.status_code == 400
    assert "Keep this evidence note" in result.text and 'value="Nurse specialist"' in result.text
    assert list_open_jobs(db_session) == []
    assert item.normalized["title"] == "Registered Nurse"


def test_open_redirect_query_requires_review():
    assert not in_scope(
        "https://hospital.example.ng/jobs?next=https://scam.example.org",
        "https://hospital.example.ng/jobs",
    )
    assert in_scope(
        "https://hospital.example.ng/jobs?utm_source=nurse.ng", "https://hospital.example.ng/jobs"
    )
