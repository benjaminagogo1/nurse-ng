"""Discovery reaches multiple publishers and carries on at approved career pages."""

from sqlalchemy import select

from app.core.config import settings
from app.models.recruitment import DiscoverySchedule, RecruitmentSource
from app.services import recruitment as registry
from app.services.recruitment_discovery import search_query
from app.services.recruitment_search import candidates_from_results
from tests.test_automatic_activation import check, staff
from tests.test_factual_opportunities import fixture
from tests.test_staff_factual_collection import activate


def test_one_publisher_cannot_fill_discovery_results():
    rows = [{'url': f'https://www.jobs.example.org/job/{i}', 'title': 'Hospital careers'}
            for i in range(30)]
    rows += [
        {'url': 'https://jobs.example.org/another', 'title': 'Same publisher without www'},
        {'url': 'https://health.example.gov.ng/jobs', 'title': 'State health recruitment'},
        {'url': 'https://ngo.example.org/internships', 'title': 'NGO internships'},
    ]
    result = candidates_from_results(rows, query='health careers', provider='searxng')
    assert len(result) == 4
    assert {row['source_url'] for row in result[-2:]} == {
        'https://health.example.gov.ng/jobs', 'https://ngo.example.org/internships',
    }
    assert all(row['country_code'] == '' for row in result)


def test_expansion_preserves_paused_schedules_and_rotates_regions(db_session, monkeypatch):
    monkeypatch.setattr(settings, 'recruitment_searxng_urls', 'http://127.0.0.1:9999')
    preview = registry.expand_opportunity_discovery(db_session, dry_run=True)
    assert len(preview['created']) == 5
    assert not db_session.scalar(select(DiscoverySchedule))
    assert len(registry.expand_opportunity_discovery(db_session)['created']) == 5
    schedule = db_session.scalar(select(DiscoverySchedule))
    schedule.enabled = False
    schedule.next_page = 12
    db_session.commit()
    assert registry.expand_opportunity_discovery(db_session)['created'] == []
    assert not schedule.enabled and schedule.next_page == 12
    payload = {'query': schedule.query, 'country_code': 'NG', 'page': 1}
    assert 'Abia' not in search_query(payload)
    assert 'Abia' in search_query({**payload, 'page': 2})
    assert 'Adamawa' in search_query({**payload, 'page': 3})


def test_approved_collector_discovers_external_portal_without_implicitly_approving_it(
    db_session, monkeypatch,
):
    from app.services import recruitment_worker as worker

    monkeypatch.setattr(worker, 'NETWORK_COOLDOWN_SECONDS', 0)
    home = 'https://hospital.example.ng/'
    portal = 'https://recruit.example.org/hospital/jobs'
    source, fetched, _ = fixture(db_session, host=home)
    activate(db_session, staff(db_session), source)
    fetched.responses[home].body += f'<a href="{portal}">Our careers portal</a>'.encode()
    assert check(db_session, source, fetched).status == 'completed'
    child = db_session.scalar(select(RecruitmentSource).where(
        RecruitmentSource.original_url == portal))
    assert child is not None and child.verification_status == 'pending'
    assert child.discovered_via == 'institution_link'
    assert not any(url == portal for url, _ in fetched.calls)
    # Re-discovery does not duplicate a site or override a prior source rejection.
    child.verification_status = 'rejected'
    db_session.commit()
    assert check(db_session, source, fetched).status == 'completed'
    children = list(db_session.scalars(select(RecruitmentSource).where(
        RecruitmentSource.original_url == portal)))
    assert len(children) == 1 and children[0].verification_status == 'rejected'
