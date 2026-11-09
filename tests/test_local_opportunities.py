"""Nigerian priority in the feed and queue, with wider early-career coverage."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.jobs import Job
from app.models.recruitment import DiscoverySchedule, RecruitmentSource
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.jobs import create_job, list_open_jobs
from app.services.opportunities import relevant_opportunity
from app.services.recruitment_discovery import (
    CAREER_WORDS,
    DISCOVERY_CATEGORIES,
    NIGERIAN_REGIONS,
    PageLinks,
    search_query,
)
from app.services.vacancy_extraction import normalize
from tests.test_recruitment import manual, observation
from tests.test_recruitment import staff as staff


@pytest.mark.parametrize("title,description,country,expected", [
    ("National Health Fellow", "Community placement", "NG", True),
    ("Nigeria Jubilee Fellows Programme", "Work placements across sectors", "NG", True),
    ("Digital Health Officer", "Data systems", "NG", True),
    ("Public Health Internship", "Training", "NG", True),
    ("Graduate Trainee Programme", "Private-sector placement", "NG", True),
    ("Intern", "Work on community health projects", "KE", True),
    ("Graduate Trainee", "Banking", "GB", False),
    ("Chief Financial Officer", "Manage a hospital's finances", "NG", False),
    ("Office Manager", "Manage public health office supplies", "NG", False),
    ("Registered Nurse", "Nursing care", "GB", True),
])
def test_relevance_includes_local_programmes_without_admitting_every_job(
    title, description, country, expected,
):
    data = dict(title=title, description=description, country=country)
    assert relevant_opportunity(data) == expected


@pytest.mark.parametrize("title,expected", [
    ("Nigeria Jubilee Fellows Programme", "fellowship"),
    ("National Health Fellow", "fellowship"),
    ("Digital Health Internship", "internship"),
    ("Graduate Trainee Programme", "graduate_programme"),
])
def test_programme_filters_preserve_original_employment_terms(title, expected):
    data = normalize({"title": title, "employmentType": "FULL_TIME"})
    assert data["job_type"] == expected
    assert data["employment_type_text"] == "FULL_TIME"


def test_feed_ranks_nigeria_before_newer_foreign_jobs_and_preserves_filters(
    db_session, staff, client,
):
    staff.account_type = "employer"
    db_session.commit()
    def post(title, country):
        return create_job(
            db_session, staff, title=title, country_code=country, organization="Example",
            location="", job_type="fellowship", work_mode="on_site", salary_min="",
            salary_max="", description="Read the programme's eligibility requirements.",
        )

    local = post("Local Fellowship", "NG")
    local.posted_at = registry.now() - timedelta(days=10)
    db_session.commit()
    international = post("Overseas Fellowship", "GB")
    unknown = post("Unspecified Fellowship", "")
    assert list_open_jobs(db_session, limit=1)[0].id == local.id
    assert {j.id for j in list_open_jobs(db_session)} == {local.id, international.id, unknown.id}
    assert [j.id for j in list_open_jobs(db_session, international_only=True)] == [international.id]
    assert [j.id for j in list_open_jobs(db_session, country_code="GB")] == [international.id]
    assert list_open_jobs(db_session, job_type="internship") == []
    page = client.get("/jobs")
    assert page.text.index("Local Fellowship") < page.text.index("Overseas Fellowship")
    page = client.get("/jobs?scope=international&type=fellowship&q=Fellowship")
    assert "Overseas Fellowship" in page.text
    assert "Local Fellowship" not in page.text and "Unspecified Fellowship" not in page.text
    links = PageLinks()
    links.feed(page.text)
    nigeria = next(url for url, label in links.links if label == "Nigeria only")
    assert parse_qs(urlsplit(nigeria).query) == {
        "country": ["NG"], "type": ["fellowship"], "q": ["Fellowship"],
    }
    assert 'name="type" form="jobs-search-form"' in page.text
    assert '<option value="fellowship" selected>' in page.text
    assert '<option value="internship">Internship</option>' in page.text
    assert 'name="scope" value="international"' in page.text
    assert "Overseas Fellowship" not in client.get("/jobs?country=NG").text


def test_queue_prefers_four_local_checks_then_one_international(db_session, staff, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    foreign = manual(
        db_session, staff, name="Foreign hospital", country_code="GB",
        website_url="https://hospital.example.uk", source_url="https://hospital.example.uk/jobs",
    )
    foreign.next_check_at = registry.now() - timedelta(days=10)
    locals_ = [manual(db_session, staff, source_url=f"https://lshsc.ng/jobs/{i}") for i in range(5)]
    db_session.commit()
    sources, _ = registry.list_sources(db_session)
    assert all(s.organization.country_code == "NG" for s in sources[:5])
    assert worker.enqueue_due(db_session) == 6
    assert worker.enqueue_due(db_session) == 0
    selected = []
    for _ in range(6):
        task = worker.run_next(db_session, executor=lambda _, p: observation(p["url"]))
        selected.append(task.source_id)
    assert set(selected[:4]).issubset({s.id for s in locals_})
    assert selected[4] == foreign.id
    assert selected[5] in {s.id for s in locals_}


def test_local_source_takes_last_queue_slot_ahead_of_worldwide_schedule(
    db_session, staff, monkeypatch,
):
    monkeypatch.setattr(settings, "recruitment_pending_task_limit", 1)
    registry.add_schedule(
        db_session, staff, name="Worldwide", provider="ror", country_code="", query="",
        interval_hours=24,
    )
    source = manual(db_session, staff)
    assert worker.enqueue_due(db_session) == 1
    assert worker.claim_next(db_session).source_id == source.id


def test_queue_admission_leaves_room_for_international_work(db_session, staff, monkeypatch):
    monkeypatch.setattr(settings, "recruitment_pending_task_limit", 5)
    for i in range(7):
        manual(db_session, staff, source_url=f"https://lshsc.ng/jobs/{i}")
    foreign = manual(
        db_session, staff, name="Foreign hospital", country_code="GB",
        website_url="https://hospital.example.uk", source_url="https://hospital.example.uk/jobs",
    )
    assert worker.enqueue_due(db_session) == 5
    from app.models.recruitment import DiscoveryTask

    queued = list(db_session.scalars(select(DiscoveryTask)))
    assert sum(t.source_id == foreign.id for t in queued) == 1
    assert all(t.schedule_id is None for t in queued)


def test_initialization_updates_only_original_worldwide_default(db_session, staff):
    default = registry.add_schedule(
        db_session, staff, name="Worldwide healthcare institutions", provider="ror",
        country_code="", query="", interval_hours=24,
    )
    default.enabled = False
    default.next_page = 7
    db_session.commit()
    registry.initialize_discovery(db_session)
    assert default.interval_hours == 168 and not default.enabled and default.next_page == 7
    assert db_session.scalar(select(DiscoverySchedule).where(
        DiscoverySchedule.country_code == "NG",
    )).interval_hours == 24
    sources = list(db_session.scalars(select(RecruitmentSource)))
    assert len(sources) == 8 and all(s.verification_status == "pending" for s in sources)
    assert all(s.organization.country_code == "NG" for s in sources)
    default.interval_hours = 72
    db_session.commit()
    assert registry.initialize_discovery(db_session) == {"schedules": 0, "sources": 0}
    assert default.interval_hours == 72
    assert db_session.scalar(select(Job)) is None


def test_queries_cover_programmes_and_each_state_plus_national_round():
    payload = {"query": "{category} {region} {country}", "country_code": "NG"}
    first_round = [
        search_query(payload | {"page": n + 1}) for n in range(len(DISCOVERY_CATEGORIES))
    ]
    assert any("youth fellowship" in q for q in first_round)
    assert any("digital health" in q for q in first_round)
    assert any("internship" in q for q in first_round)
    for n, region in enumerate(NIGERIAN_REGIONS, start=1):
        assert region in search_query(payload | {"page": n * len(DISCOVERY_CATEGORIES) + 1})
    national = search_query(payload | {"page": 1})
    assert national == "ministry of health Nigeria"
    for label in ["Fellowships", "Become a Fellow", "Digital health", "Graduate programme"]:
        assert CAREER_WORDS.search(label)
