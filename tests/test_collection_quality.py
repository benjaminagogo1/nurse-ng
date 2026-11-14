"""Real failure shapes: ordinary salary paragraphs, non-vacancy pages and repeated sources."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.vacancies import VacancyEvent, VacancyRecord
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.announcement_extraction import announcement_links, extract_announcements
from app.services.factual_opportunities import factual_records
from app.services.jobs import list_open_jobs, salary_label
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancies import ingest_page, reconcile_pending_quality
from app.services.vacancy_extraction import normalize
from app.services.vacancy_quality import canonical_vacancy_url
from app.services.vacancy_salary import salary_from_text
from tests.test_automatic_activation import check
from tests.test_automatic_activation import staff as make_staff
from tests.test_factual_opportunities import fixture
from tests.test_staff_factual_collection import activate
from tests.test_vacancy_ingestion import (  # noqa: F401
    collect,
    no_cooldown,
    page_result,
    posting,
    source,
    staff,
)


@pytest.mark.parametrize("title", [
    "Medical & Pharmaceutical Jobs in Nigeria",
    "Internship & volunteer Medical & Pharmaceutical Jobs in Nigeria",
    "Graduate Jobs in Nigeria",
    "Medical Library Services",
    "School of Nursing Forms Available on Sale for 2024 in Nigeria",
    "LUTH School of Nursing Admission Form 2024/2025",
    "Premier HealthCare",
    "15 ROTC students assured spots in nursing | UNC-Chapel Hill",
    "Medical Education",
    "Clinical Professionals",
    "Non-Clinical Professionals",
    "Recent changes in regulatory aspect of clinical trials in India",
    "Clinical Trial Related Injury: Note on Formula to Determine Compensation",
    "The Graduate School - The University of North Carolina at Chapel Hill",
    "Nursing at OhioHealth",
    "GBV and Public Health: Short Course in Bhopal, 2026",
    "Residential Short-Course on GBV & Public Health in Bhopal – Apply Now!",
    "Mental Health and Sickle Cell Disease: What Policy Leaves Unseen",
])
def test_non_vacancy_pages_are_not_extracted_even_when_they_mention_applications(title):
    body = f"<main><h1>{title}</h1><p>Applications open. Apply now in Nigeria.</p></main>".encode()
    assert extract_announcements(body, "https://example.ng/announcement") == []


def test_employer_category_page_does_not_become_an_individual_vacancy():
    body = b'<main><h1>MeCure Healthcare Limited Recruitment</h1><p>Apply in Nigeria.</p></main>'
    assert extract_announcements(body, 'https://www.myjobmag.com/jobs-at/mecure') == []


def test_detail_discovery_prioritizes_vacancies_and_does_not_visit_health_news():
    body = b'''<main>
        <a href="/news">Mental Health and Sickle Cell Disease: What Policy Leaves Unseen</a>
        <a href="/clinical-professionals">Clinical Professionals</a>
        <a href="/jobs/nurse">Registered Nurse</a>
        <a href="/careers">Careers</a>
    </main>'''
    links = announcement_links(body, 'https://example.ng/', 'https://example.ng/',
                               include_channels=True)
    assert links[0] == 'https://example.ng/jobs/nurse'
    assert set(links[1:]) == {'https://example.ng/careers',
                             'https://example.ng/clinical-professionals'}


def test_explicit_position_field_keeps_an_unfamiliar_health_role_for_review():
    body = (b'<main><h1>Public Health Data Lead</h1><p>Position: Data Lead</p>'
            b'<p>Apply now.</p></main>')
    assert extract_announcements(body, 'https://example.ng/recruitment')


@pytest.mark.parametrize('title', [
    'Community Health Extension Worker', 'Nursing Educator', 'Public Health Fellowship',
])
def test_individual_health_roles_and_programmes_remain_collectable(title):
    body = f'<main><h1>{title}</h1><p>Apply now in Nigeria.</p></main>'.encode()
    assert extract_announcements(body, 'https://example.ng/recruitment')


@pytest.mark.parametrize("title", ["Medical Library Services", "Nursing Jobs in Nigeria"])
def test_non_vacancies_in_structured_data_cannot_publish(db_session, source, title):  # noqa: F811
    collect(db_session, source, [posting(title=title)])
    assert list_open_jobs(db_session) == []
    assert db_session.scalar(select(VacancyRecord)).state == 'pending'


@pytest.mark.parametrize(("text", "expected"), [
    ("Remuneration:\nMonthly gross of NGN\n181,440\nBenefits",
     {"currency": "NGN", "unit": "MONTH", "value": "181440", "basis": "gross"}),
    ("Salary: ₦200k–₦300k per month",
     {"currency": "NGN", "unit": "MONTH", "minValue": "200000", "maxValue": "300000"}),
    ("Salary: GBP 18.50 per hour", {"currency": "GBP", "unit": "HOUR", "value": "18.50"}),
    ("Annual salary: USD 50,000 to 60,000",
     {"currency": "USD", "unit": "YEAR", "minValue": "50000", "maxValue": "60000"}),
    ("Salary: up to NGN 300,000 monthly",
     {"currency": "NGN", "unit": "MONTH", "maxValue": "300000"}),
    ("Salary: NGN 200,000", {"currency": "NGN", "unit": "", "value": "200000"}),
    ("Expected salary: NGN 900,000 monthly", {}),
    ("Salary Alignment\nAre you comfortable with the salary listed on the job post?", {}),
    ("Salary: $500 monthly", {}),
    ("Salary: -NGN 500 monthly", {}),
    ("Salary: NGN 200,000 monthly\nSalary: NGN 300,000 monthly", {}),
    ("Salary: Not disclosed\nApplication fee: NGN 5,000", {}),
    ("Salary\nNegotiable\nTransport allowance: NGN 20,000 monthly", {}),
    ("Salary: Not disclosed. Application fee: NGN 5,000", {}),
    ("Salary: NGN 200,000 monthly\nBenefits:\nAnnual bonus: NGN 50,000",
     {"currency": "NGN", "unit": "MONTH", "value": "200000"}),
    ("Annual remuneration: NGN 2,000,000",
     {"currency": "NGN", "unit": "YEAR", "value": "2000000"}),
])
def test_salary_reads_explicit_offered_amount_without_guessing(text, expected):
    assert salary_from_text(text) == expected


def test_eha_salary_paragraph_reaches_public_listing_and_refreshes_same_job(
    db_session, monkeypatch, client,
):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session, host="https://hospital.example.ng/")
    activate(db_session, make_staff(db_session), item)
    salary_html = (
        b"<p><strong>Remuneration:</strong></p><p>Monthly gross of NGN\n181,440</p>"
        b"<p>Benefits</p><p>Health benefit</p>"
    )
    fetched.responses[target].body = fetched.responses[target].body.replace(
        b"</main>", salary_html + b"</main>"
    )
    check(db_session, item, fetched)
    job = list_open_jobs(db_session)[0]
    identifier = job.id
    assert salary_label(job) == "NGN 181,440 per month · gross"
    assert "NGN 181,440 per month" in client.get(f"/jobs/{job.id}").text
    fetched.responses[target].body = fetched.responses[target].body.replace(b"181,440", b"200,000")
    check(db_session, item, fetched)
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1 and jobs[0].id == identifier
    assert salary_label(jobs[0]) == "NGN 200,000 per month · gross"


def test_one_page_salary_is_not_assigned_to_multiple_structured_jobs():
    import base64

    data = page_result([posting(), posting(identifier="second", title="Medical Intern")])
    body = base64.b64decode(data["body_base64"]) + b"<p>Salary: NGN 500,000 monthly</p>"
    page = FetchedPage(data["observed_url"], 200, "text/html", body)
    records = factual_records(page, {"scope": "https://hospital.example.ng/",
                                    "organisation": "Example Hospital"})
    assert len(records) == 2
    assert all(not normalize(raw)["salary"] for raw in records)


def test_identical_structured_copies_can_use_the_single_job_salary():
    import base64

    raw = posting()
    data = page_result([raw, raw])
    body = base64.b64decode(data["body_base64"]) + b"<p>Salary: NGN 500,000 monthly</p>"
    page = FetchedPage(data["observed_url"], 200, "text/html", body)
    records = factual_records(page, {"scope": "https://hospital.example.ng/",
                                    "organisation": "Example Hospital"})
    assert len(records) == 1
    assert normalize(records[0])["salary"] == {
        "currency": "NGN", "unit": "MONTH", "value": "500000",
    }


def test_duplicate_pending_sources_keep_evidence_but_create_one_review(
    db_session, source,  # noqa: F811
):
    from copy import deepcopy

    from app.models.recruitment import RecruitmentSource

    others = []
    for suffix in ("two", "three"):
        values = {column.name: deepcopy(getattr(source, column.name))
                  for column in RecruitmentSource.__table__.columns
                  if column.name not in {"id", "created_at", "updated_at"}}
        values.update(original_url=f"https://hospital.example.ng/{suffix}", url_key=suffix)
        other = RecruitmentSource(**values)
        db_session.add(other)
        db_session.flush()
        others.append(other)
    raw = posting(validThrough="next month")
    for index, item in enumerate([source, *others]):
        ingest_page(db_session, item, page_result([raw]), registry.now() + timedelta(seconds=index))
        db_session.commit()
    records = list(db_session.scalars(select(VacancyRecord).order_by(VacancyRecord.first_seen_at)))
    assert [r.state for r in records] == ["pending", "duplicate", "duplicate"]
    assert all(r.raw_record == raw for r in records)
    assert all(r.normalized['_duplicate_of'] == str(records[0].id) for r in records[1:])
    assert db_session.scalar(select(func.count()).select_from(VacancyEvent)) == 3
    # Materially different facts need a separate review, even at the same URL.
    ingest_page(db_session, others[0],
                page_result([posting(validThrough="next month", title="Nurse manager")]),
                registry.now() + timedelta(seconds=10))
    db_session.commit()
    db_session.refresh(records[1])
    assert records[1].state == "pending" and '_duplicate_of' not in records[1].normalized


def test_existing_queue_cleanup_is_audited_and_dry_run_preserves_records(db_session, source):  # noqa: F811
    ingest_page(db_session, source, page_result([posting(
        title="Medical Library Services", validThrough="",
    )]), registry.now())
    db_session.commit()
    record = db_session.scalar(select(VacancyRecord))
    assert reconcile_pending_quality(db_session, dry_run=True) == {"excluded": 1, "duplicates": 0}
    db_session.refresh(record)
    assert record.state == "pending"
    assert reconcile_pending_quality(db_session) == {"excluded": 1, "duplicates": 0}
    db_session.refresh(record)
    assert record.state == "rejected" and record.raw_record["title"] == "Medical Library Services"
    assert db_session.scalar(select(VacancyEvent).where(VacancyEvent.action == "quality_excluded"))


def test_tracking_links_refresh_the_same_record_and_public_job(db_session, source):  # noqa: F811
    raw = posting(identifier=None, url='https://hospital.example.ng/jobs/123?job_id=123&utm_source=a')
    collect(db_session, source, [raw])
    first_record = db_session.scalar(select(VacancyRecord))
    first_job = list_open_jobs(db_session)[0]
    changed = {**raw, 'url': 'https://hospital.example.ng/jobs/123?job_id=123&utm_source=b'}
    collect(db_session, source, [changed])
    assert db_session.scalar(select(func.count()).select_from(VacancyRecord)) == 1
    assert list_open_jobs(db_session)[0].id == first_job.id
    db_session.refresh(first_record)
    assert first_record.raw_record['url'] == changed['url']
    assert first_record.normalized['announcement_url'] == changed['url']
    assert canonical_vacancy_url(changed['url']) == 'https://hospital.example.ng/jobs/123?job_id=123'
    assert canonical_vacancy_url('https://hospital.example.ng/jobs?job_id=456') != (
        canonical_vacancy_url('https://hospital.example.ng/jobs?job_id=123')
    )


def test_identical_embedded_job_records_do_not_create_a_false_conflict(db_session, source):  # noqa: F811
    raw = posting()
    collect(db_session, source, [raw, raw])
    assert len(list_open_jobs(db_session)) == 1
    assert db_session.scalar(select(VacancyRecord)).issues == []


def test_explicit_country_employer_and_scalar_salary_variants_are_preserved():
    data = normalize(posting(hiringOrganization='Example Hospital', employmentType='full_time',
        jobLocation={'address': {'addressCountry': {'name': 'Nigeria'}}},
        baseSalary={'currency': 'ngn', 'value': 181440}))
    assert data['country'] == 'NG' and data['employer'] == 'Example Hospital'
    assert data['job_type'] == 'full_time'
    assert data['salary'] == {'currency': 'NGN', 'unit': '', 'value': '181440'}


def test_malformed_salary_period_does_not_crash_collection():
    data = normalize(posting(baseSalary={
        'currency': 'NGN', 'value': {'value': 10000, 'unitText': {'name': 'MONTH'}},
    }))
    assert data['salary'] == {} and data['title'] == 'Registered Nurse'


def test_unchanged_source_facts_receive_updated_normalization(db_session, source):  # noqa: F811
    from copy import deepcopy

    raw = posting(baseSalary={'currency': 'NGN', 'value': {
        'value': 181440, 'unitText': 'MONTH',
    }}, _salary_basis='gross')
    collect(db_session, source, [raw])
    record = db_session.scalar(select(VacancyRecord))
    job = list_open_jobs(db_session)[0]
    identifier = job.id
    legacy = deepcopy(record.normalized)
    legacy['salary'].pop('basis')
    record.normalized = legacy
    job.normalized_data = legacy
    db_session.commit()
    collect(db_session, source, [raw])
    refreshed = list_open_jobs(db_session)[0]
    assert refreshed.id == identifier
    assert salary_label(refreshed) == 'NGN 181,440 per month · gross'
    assert any(event.details.get('normalization_changed') for event in
               db_session.scalars(select(VacancyEvent).where(VacancyEvent.record_id == record.id)))


def test_rotating_batches_keep_nursing_links_ahead_of_channels():
    body = ('<a href="/careers">Careers</a>' + ''.join(
        f'<a href="/jobs/nurse-{i}">Registered Nurse {i}</a>' for i in range(5)
    ) + '<a href="/jobs/medical-intern">Medical Intern</a>').encode()
    visited = set()
    for offset in range(0, 20, 4):
        links = announcement_links(body, 'https://example.ng/', 'https://example.ng/',
                                   include_channels=True, page_offset=offset)
        assert all('/jobs/nurse-' in url for url in links[:2])
        assert links[2] == 'https://example.ng/jobs/medical-intern'
        assert links[3] == 'https://example.ng/careers'
        visited.update(links[:2])
    assert len(visited) == 5


def test_factual_index_ignores_unrelated_structured_adverts():
    import base64

    data = page_result([posting(title='Head of Aquaculture'),
                        posting(identifier='nurse', title='Registered Nurse'),
                        posting(identifier='intern', title='Procurement Intern')])
    page = FetchedPage(data['observed_url'], 200, 'text/html',
                       base64.b64decode(data['body_base64']))
    facts = factual_records(page, {'scope': 'https://hospital.example.ng/',
                                   'organisation': 'Example Hospital'})
    assert {row['title'] for row in facts} == {'Registered Nurse', 'Procurement Intern'}


def test_unrelated_factual_queue_cleanup_is_previewable_and_preserves_reviews(
    db_session, source,  # noqa: F811
):
    collect(db_session, source, [posting(title='Head of Aquaculture')])
    record = db_session.scalar(select(VacancyRecord))
    record.normalized = {**record.normalized, '_index': {'publisher': 'Example'}}
    db_session.commit()
    preview = reconcile_pending_quality(db_session, dry_run=True, exclude_unrelated=True)
    assert preview['excluded'] == 1
    db_session.refresh(record)
    assert record.state == 'pending'
    record.normalized = {**record.normalized, '_review': {'nursing_confirmed': True}}
    db_session.commit()
    assert reconcile_pending_quality(db_session, exclude_unrelated=True)['excluded'] == 0
    record.normalized = {key: value for key, value in record.normalized.items() if key != '_review'}
    db_session.commit()
    assert reconcile_pending_quality(db_session, exclude_unrelated=True)['excluded'] == 1
    db_session.refresh(record)
    assert record.state == 'rejected'
