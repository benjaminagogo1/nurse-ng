"""Reuse decisions must bind activation, network requests and public vacancy reads."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.jobs import Job
from app.models.recruitment import SourceEvent
from app.models.user import User
from app.models.vacancies import VacancySnapshot
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.jobs import effective_job_status, list_open_jobs
from app.services.recruitment_fetch import FetchedPage, FetchError
from app.services.vacancies import activation_blockers, collector_authorized, configure_collector
from tests.helpers import register_and_sign_in
from tests.test_recruitment import approve, manual
from tests.test_recruitment_fetch import ScriptedFetcher
from tests.test_vacancy_ingestion import collect, page_result, posting


@pytest.fixture
def staff(db_session):
    actor = User(phone="+2348012345678", hashed_password="unused", is_staff=True)
    db_session.add(actor)
    db_session.commit()
    return actor


def grant(source, **changes):
    return {
        "basis": "legal_basis",
        "url_prefix": source.original_url,
        **{right: True for right in registry.REUSE_RIGHTS},
        **changes,
    }


def enable(db, staff, source, prefix=None):
    configure_collector(
        db,
        staff,
        source,
        revision=source.revision,
        enabled=True,
        url_prefix=prefix or source.original_url,
        timezone="Africa/Lagos",
        note="Synthetic scope in isolated test database",
        reference="https://example.org/evidence",
    )


@pytest.mark.parametrize("missing", ["basis", *registry.REUSE_RIGHTS])
def test_public_government_page_does_not_infer_missing_rights(db_session, staff, missing):
    source = manual(db_session, staff)
    reuse = grant(source)
    reuse.pop(missing)
    with pytest.raises(registry.RecruitmentError):
        approve(db_session, staff, source, reuse=reuse)
    assert source.verification_status == "pending"
    assert source.original_url == "https://lshsc.ng/recruitment"
    assert not collector_authorized(source)


def test_documented_legal_basis_does_not_require_a_separate_licence(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source, reuse=grant(source))
    assert registry.collection_authorized(source)
    enable(db_session, staff, source)
    assert collector_authorized(source)
    assert activation_blockers(source) == []
    entry = db_session.scalar(select(SourceEvent).where(SourceEvent.kind == "approve"))
    assert entry.details["reuse"]["basis"] == "legal_basis"
    assert entry.actor_id == staff.id and entry.details["policy_version"] == 2


def test_collector_cannot_expand_granted_url_scope(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source, reuse=grant(source))
    with pytest.raises(registry.RecruitmentError, match="exceed"):
        enable(db_session, staff, source, "https://lshsc.ng")
    assert source.collection_adapter == ""
    enable(db_session, staff, source)
    assert collector_authorized(source)


@pytest.mark.parametrize(
    "scope",
    [
        "https://other.example.org",
        "https://lshsc.ng/other",
        "https://lshsc.ng/?q=jobs",
    ],
)
def test_unrelated_reuse_scope_cannot_approve_source(db_session, staff, scope):
    source = manual(db_session, staff)
    with pytest.raises(registry.RecruitmentError, match="scope"):
        approve(db_session, staff, source, reuse=grant(source, url_prefix=scope))


def test_reapproval_requires_collector_reconfiguration(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source, reuse=grant(source))
    enable(db_session, staff, source)
    approve(db_session, staff, source, reuse=grant(source))
    assert source.collection_adapter == source.vacancy_url_prefix == ""
    assert not collector_authorized(source)
    enable(db_session, staff, source)
    assert collector_authorized(source)


@pytest.mark.parametrize("right", list(registry.REUSE_RIGHTS))
def test_missing_right_hides_published_jobs_without_waiting_for_worker(db_session, staff, right):
    source = manual(
        db_session,
        staff,
        name="Example Hospital",
        website_url="https://hospital.example.ng",
        source_url="https://hospital.example.ng/recruitment",
    )
    approve(db_session, staff, source)
    enable(db_session, staff, source, "https://hospital.example.ng")
    collect(db_session, source, [posting()])
    job = db_session.scalar(select(Job))
    assert list_open_jobs(db_session) == [job]
    setattr(source, right, False)
    db_session.commit()
    assert list_open_jobs(db_session) == []
    assert effective_job_status(job) == "unconfirmed"
    assert not collector_authorized(source)


def test_reapproval_during_fetch_cannot_save_stale_snapshot(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source, reuse=grant(source))
    enable(db_session, staff, source)
    worker.enqueue_due(db_session)

    def execute(kind, payload):
        assert payload["collect_vacancies"]
        assert payload["reuse_url_prefix"] == source.original_url
        approve(db_session, staff, source, reuse=grant(source))
        return page_result([posting()])

    task = worker.run_next(db_session, executor=execute)
    assert task.status == "cancelled"
    assert db_session.scalar(select(func.count()).select_from(VacancySnapshot)) == 0


def test_same_origin_redirect_outside_scope_is_not_fetched():
    url = "https://example.org/recruitment"
    fetcher = ScriptedFetcher({url: FetchedPage("/unrelated", 302, "text/html", b"")})
    with pytest.raises(FetchError, match="scope"):
        fetcher.get(url, robots=False, allowed_url_prefix=url)
    assert fetcher.calls == [(url, None)]


def test_pending_source_page_explains_activation_and_legal_basis(client, db_session):
    register_and_sign_in(client)
    staff = db_session.scalar(select(User))
    staff.is_staff = True
    db_session.commit()
    source = manual(db_session, staff)
    page = client.get(f"/recruitment/sources/{source.id}")
    assert page.status_code == 200
    assert "Not enabled" in page.text and 'value="legal_basis"' in page.text
    assert "A separate licence is not mandatory" in page.text
    assert "original snapshot retention" in page.text
    assert 'name="allow_republication"' in page.text
    assert page.headers["Cache-Control"] == "no-store"


def test_expired_reuse_approval_disables_collection(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source, reuse=grant(source))
    enable(db_session, staff, source)
    source.approval_expires_at = registry.now() - timedelta(seconds=1)
    db_session.commit()
    assert not collector_authorized(source)
    assert any("current source approval" in reason for reason in activation_blockers(source))
