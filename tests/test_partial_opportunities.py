"""Incomplete adverts stay discoverable, with source facts and uncertainty intact."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.vacancies import VacancyRecord
from app.services.jobs import job_card, list_open_jobs
from app.services.recruitment import now
from app.services.vacancies import reassess_incomplete_records
from tests.test_vacancy_ingestion import (  # noqa: F401
    collect,
    no_cooldown,
    posting,
    source,
    staff,
)


@pytest.mark.parametrize('title', [
    'Federal Health Internship', 'State Health Fellowship', 'NGO Graduate Programme',
    'Pharmacist', 'Midwife', 'Dental Assistant',
])
def test_title_and_original_link_can_publish_without_optional_details(
    db_session, source, client, title,  # noqa: F811
):
    collect(db_session, source, [posting(
        title=title, hiringOrganization={}, jobLocation={}, description='',
        validThrough='', datePosted='', employmentType='', qualifications='',
        baseSalary={}, experienceRequirements='',
    )])
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.organization == job.country_code == job.description == ''
    assert job.closes_at is None
    assert db_session.scalar(select(VacancyRecord)).issues == []
    card = job_card(job)
    assert card['organization'] == 'Organisation not stated'
    assert card['status_label'] == 'Check availability'
    assert card['date_label'] == 'First listed'
    page = client.get(f'/jobs/{job.id}')
    assert page.status_code == 200
    for text in [title, 'Organisation not stated', 'Not stated',
                 'Check availability', 'Eligibility requirements are not supplied']:
        assert text in page.text
    assert card['announcement_url'] in page.text
    assert title in client.get('/jobs').text
    # Missing facts are allowed; a stale check does not become a fresh observation.
    job.confirmed_at = now() - timedelta(hours=49)
    db_session.commit()
    assert list_open_jobs(db_session) == []


def test_missing_details_do_not_make_an_expired_advert_current(db_session, source):  # noqa: F811
    collect(db_session, source, [posting(
        hiringOrganization={}, jobLocation={}, description='', datePosted='',
        validThrough=(now() - timedelta(days=1)).isoformat(),
    )])
    assert list_open_jobs(db_session) == []


@pytest.mark.parametrize('condition', ['fresh', 'stale', 'revoked', 'rejected', 'conflict'])
def test_reassessment_preserves_observation_time_and_previous_decisions(
    db_session, source, condition,  # noqa: F811
):
    collect(db_session, source, [posting(validThrough='', hiringOrganization={})])
    job = list_open_jobs(db_session)[0]
    record = db_session.scalar(select(VacancyRecord))
    checked = now() - timedelta(hours=49 if condition == 'stale' else 2)
    record.last_seen_at = checked
    record.state = 'rejected' if condition == 'rejected' else 'pending'
    record.issues = ['conflict: source records disagree'] if condition == 'conflict' else [
        'closing_date: missing or ambiguous deadline', 'employer: required',
    ]
    job.status = 'unconfirmed'
    if condition == 'revoked':
        source.verification_status = 'revoked'
    db_session.commit()
    preview = reassess_incomplete_records(db_session, dry_run=True)
    db_session.refresh(job)
    assert job.status == 'unconfirmed'
    result = reassess_incomplete_records(db_session)
    assert result == preview
    jobs = list_open_jobs(db_session)
    if condition == 'fresh':
        assert [item.id for item in jobs] == [job.id]
        assert jobs[0].confirmed_at.replace(tzinfo=None) == checked.replace(tzinfo=None)
        assert result['published'] == 1
    else:
        assert jobs == [] and result['published'] == 0
