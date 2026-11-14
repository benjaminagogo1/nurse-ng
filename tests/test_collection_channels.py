"""A focused channel improves yield without granting any additional collection rights."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models.recruitment import RecruitmentSource, SourceEvent
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.announcement_extraction import announcement_links
from app.services.jobs import list_open_jobs
from app.services.recruitment_fetch import FetchedPage, FetchError
from app.services.recruitment_indexing import select_collection_channel
from app.services.vacancy_extraction import collect_page
from tests.test_automatic_activation import check, staff
from tests.test_factual_opportunities import fixture
from tests.test_staff_factual_collection import activate
from tests.test_vacancy_ingestion import posting

HOST = 'https://hospital.example.ng/'
CHANNEL = HOST + 'jobs-by-title/nurse'


def setup(db, monkeypatch):
    monkeypatch.setattr(worker, 'NETWORK_COOLDOWN_SECONDS', 0)
    source, fetched, old = fixture(db, host=HOST)
    activate(db, staff(db), source)
    fetched.responses[CHANNEL] = FetchedPage(CHANNEL, 200, 'text/html', (
        '<h1>Nurse Jobs in Nigeria</h1>' + ''.join(
            f'<a href="{HOST}job/nurse-{i}">Registered Nurse {i}</a>' for i in range(9)
        )
    ).encode())
    for i in range(9):
        url = f'{HOST}job/nurse-{i}'
        raw = posting(identifier=f'nurse-{i}', title=f'Registered Nurse {i}', url='')
        structured = json.dumps(raw).replace('<', '\\u003c')
        fetched.responses[url] = FetchedPage(url, 200, 'text/html', (
            f'<h1>Registered Nurse {i} at Example Hospital</h1>'
            '<script type="application/ld+json">' + structured + '</script>'
        ).encode())
    return source, fetched, old


def test_preview_and_idempotent_configuration_preserve_approval(db_session, monkeypatch):
    source, _, _ = setup(db_session, monkeypatch)
    before = dict(source.activation_review)
    revision = source.revision
    assert select_collection_channel(db_session, source, CHANNEL, dry_run=True)['changed']
    assert source.activation_review == before and source.revision == revision
    assert select_collection_channel(db_session, source, CHANNEL)['changed']
    assert source.revision == revision + 1
    assert source.activation_review['evidence']['scope'] == before['evidence']['scope']
    assert source.activation_review['evidence']['requested_url'] == source.original_url
    assert not source.allow_republication and not source.allow_snapshot_retention
    assert not select_collection_channel(db_session, source, CHANNEL)['changed']
    events = list(db_session.scalars(select(SourceEvent).where(
        SourceEvent.kind == 'collection_channel_selected')))
    assert len(events) == 1 and events[0].actor_id is None


@pytest.mark.parametrize('state', ['revoked', 'paused', 'expired', 'outside'])
def test_channel_selection_cannot_bypass_approval(db_session, monkeypatch, state):
    source, _, _ = setup(db_session, monkeypatch)
    if state == 'revoked':
        source.verification_status = 'revoked'
    elif state == 'paused':
        source.automation_status = 'paused'
    elif state == 'expired':
        source.approval_expires_at = registry.now() - timedelta(days=1)
    db_session.commit()
    channel = 'https://another.example.ng/jobs' if state == 'outside' else CHANNEL
    with pytest.raises(ValueError):
        select_collection_channel(db_session, source, channel)


def test_channel_selection_does_not_overwrite_a_concurrent_source_change(db_session, monkeypatch):
    source, _, _ = setup(db_session, monkeypatch)
    db_session.execute(
        update(RecruitmentSource).where(RecruitmentSource.id == source.id)
        .values(revision=source.revision + 1, verification_status='revoked')
        .execution_options(synchronize_session=False)
    )
    # Keep the caller's source stale while persisting the concurrent update.
    expire = db_session.expire_on_commit
    db_session.expire_on_commit = False
    db_session.commit()
    db_session.expire_on_commit = expire
    with pytest.raises(ValueError, match='source changed'):
        select_collection_channel(db_session, source, CHANNEL)
    db_session.refresh(source)
    assert source.verification_status == 'revoked'
    assert 'collection_channel' not in source.activation_review['evidence']
    assert not db_session.scalar(select(SourceEvent).where(
        SourceEvent.kind == 'collection_channel_selected'))


def test_real_worker_collects_three_rotating_jobs_within_four_detail_requests(
    db_session, monkeypatch,
):
    source, fetched, old = setup(db_session, monkeypatch)
    select_collection_channel(db_session, source, CHANNEL)
    for _ in range(3):
        fetched.calls.clear()
        task = check(db_session, source, fetched)
        assert task.status == 'completed', task.message
        calls = [url for url, _ in fetched.calls if not url.endswith('/robots.txt')]
        assert calls[:2] == [HOST, CHANNEL]
        assert len(calls) == 5  # Original page plus one channel and three job details.
        assert old not in calls
    jobs = list_open_jobs(db_session)
    assert len(jobs) >= 5
    assert all(job.title.startswith('Registered Nurse') for job in jobs)
    assert all(job.normalized_data['announcement_url'].startswith(HOST + 'job/') for job in jobs)


def test_tampered_channel_is_blocked_before_its_request(db_session, monkeypatch):
    source, fetched, _ = setup(db_session, monkeypatch)
    evidence = {**source.activation_review['evidence'],
                'collection_channel': 'https://other.example.ng/jobs'}
    with pytest.raises(FetchError, match='outside approved scope'):
        collect_page({'url': HOST, 'reuse_url_prefix': HOST, 'collection_adapter': 'factual_index',
                      'index_evidence': evidence}, fetched)
    assert not any('other.example' in url for url, _ in fetched.calls)


def test_channel_publishes_midwifery_and_early_career_roles(db_session, monkeypatch):
    source, fetched, _ = setup(db_session, monkeypatch)
    titles = ['Midwife', 'Community Health Extension Worker', 'Medical Intern']
    fetched.responses[CHANNEL].body = ('<h1>Healthcare Jobs in Nigeria</h1>' + ''.join(
        f'<a href="{HOST}job/role-{i}">{title}</a>' for i, title in enumerate(titles)
    )).encode()
    for i, title in enumerate(titles):
        url = f'{HOST}job/role-{i}'
        structured = json.dumps(posting(identifier=f'role-{i}', title=title, url=url))
        fetched.responses[url] = FetchedPage(url, 200, 'text/html', (
            f'<h1>{title} at Example Hospital</h1><script type="application/ld+json">'
            + structured.replace('<', '\\u003c') + '</script>'
        ).encode())
    select_collection_channel(db_session, source, CHANNEL)
    assert check(db_session, source, fetched).status == 'completed'
    assert {job.title for job in list_open_jobs(db_session)} == set(titles)


def test_jobberman_filters_do_not_displace_individual_adverts():
    links = announcement_links(
        b'<a href="/jobs/medical-pharmaceutical?industry=healthcare">Healthcare Jobs</a>'
        b'<a href="/jobs/medical-pharmaceutical/internship-graduate">Medical Internships</a>'
        b'<a href="/listings/pharmacist-123">Pharmacist</a>'
        b'<a href="/listings/dental-assistant-456">Dental Assistant</a>',
        'https://www.jobberman.com/jobs', 'https://www.jobberman.com/', include_channels=True,
    )
    assert links[:2] == ['https://www.jobberman.com/listings/pharmacist-123',
                         'https://www.jobberman.com/listings/dental-assistant-456']


def test_nursing_category_never_displaces_individual_roles():
    links = announcement_links(
        b'<a href="/jobs-by-title/nurse">Registered Nurse</a>'
        b'<a href="/job/nurse">Registered Nurse at Hospital</a>',
        'https://www.myjobmag.com/', 'https://www.myjobmag.com/', include_channels=True,
    )
    assert links[0] == 'https://www.myjobmag.com/job/nurse'
