"""Discovery observations, review gates, durable work and private administration."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.jobs import Job
from app.models.recruitment import (
    DiscoverySchedule,
    RecruitmentSource,
    SourceEvent,
)
from app.models.user import User
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.recruitment_discovery import DISCOVERY_CATEGORIES, execute_discovery, search_query
from app.services.recruitment_fetch import FetchedPage
from tests.helpers import csrf_from, register_and_sign_in


@pytest.fixture(autouse=True)
def fast_queue(monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)


@pytest.fixture
def staff(db_session):
    user = User(phone="+2348012345678", hashed_password="unused", is_staff=True)
    db_session.add(user)
    db_session.commit()
    return user


def manual(db, staff, **overrides):
    values = dict(
        name="Lagos State Health Service Commission",
        category="health_commission",
        country_code="NG",
        location="Lagos",
        website_url="https://lshsc.ng",
        source_url="https://lshsc.ng/recruitment",
    )
    return registry.register_manual_source(db, staff, **(values | overrides))


def approve(db, staff, source, **overrides):
    values = dict(
        revision=source.revision,
        action="approve",
        note="Reviewed official evidence",
        method="html",
        reuse={
            "basis": "published_licence",
            "url_prefix": source.organization.website_url,
            **{right: True for right in registry.REUSE_RIGHTS},
        },
        expires_at=registry.now() + timedelta(days=90),
        checks={
            key: {"note": f"Recorded {key} finding", "url": "https://example.org/evidence"}
            for key in registry.CHECKS
        },
    )
    registry.review_source(db, staff, source, **(values | overrides))


def observation(url="https://lshsc.ng/recruitment", **overrides):
    return (
        dict(
            ok=True,
            outcome="page_checked",
            observed_url=url,
            canonical_hint="",
            content_hash="a" * 64,
            title="Recruitment",
            links=[],
            terms_links=[],
        )
        | overrides
    )


class DirectoryFixture:
    def __init__(self):
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if url.startswith("https://api.ror.org/"):
            rows = []
            for identity, code, domain in [
                ("012345678", "NG", "hospital.example.ng"),
                ("098765432", "NZ", "hospital.example.nz"),
            ]:
                rows.append(
                    {
                        "id": "https://ror.org/" + identity,
                        "types": ["healthcare"],
                        "names": [{"value": "Unseen hospital " + code, "types": ["ror_display"]}],
                        "links": [{"type": "website", "value": "https://" + domain}],
                        "locations": [{"geonames_details": {"country_code": code, "name": "City"}}],
                    }
                )
            return FetchedPage(
                url,
                200,
                "application/json",
                json.dumps({"items": rows, "number_of_results": 2}).encode(),
            )
        return FetchedPage(
            url, 200, "text/html", b'<title>Hospital</title><a href="/careers">Careers</a>'
        )


def test_directory_to_new_institution_to_recruitment_page_stays_pending(db_session, staff):
    db = db_session
    registry.add_schedule(
        db, staff, name="World", provider="ror", country_code="", query="", interval_hours=24
    )
    fixture = DirectoryFixture()

    def executor(kind, payload):
        return execute_discovery(kind, payload, fetcher=fixture)

    assert worker.enqueue_due(db) == 1
    assert worker.enqueue_due(db) == 0
    assert worker.run_next(db, executor=executor).result_count == 2
    assert worker.enqueue_due(db) == 2
    for _ in range(2):
        assert worker.run_next(db, executor=executor).result_count == 1
    sources = list(db.scalars(select(RecruitmentSource)))
    assert len(sources) == 4
    assert {s.organization.country_code for s in sources} == {"NG", "NZ"}
    assert all(s.verification_status == "pending" for s in sources)
    assert all(not registry.collection_authorized(s) for s in sources)
    assert db.scalar(select(func.count()).select_from(Job)) == 0
    # Rediscovery neither duplicates nor resets source state.
    source = sources[0]
    registry.review_source(
        db, staff, source, revision=source.revision, action="reject", note="Evidence insufficient"
    )
    schedule = db.scalar(select(DiscoverySchedule))
    schedule.next_run_at = registry.now() - timedelta(seconds=1)
    db.commit()
    worker.enqueue_due(db)
    for _ in range(3):
        worker.run_next(db, executor=executor)
    assert db.scalar(select(func.count()).select_from(RecruitmentSource)) == 4
    db.refresh(source)
    assert source.verification_status == "rejected"
    assert fixture.requests[0][1]["allowed_origin"] == "https://api.ror.org"


def test_initialization_is_idempotent_and_keeps_exact_user_url(db_session):
    assert registry.initialize_discovery(db_session) == {"schedules": 2, "sources": 5}
    assert registry.initialize_discovery(db_session) == {"schedules": 0, "sources": 0}
    assert (
        db_session.scalar(select(RecruitmentSource).where(
            RecruitmentSource.original_url == "https://lshsc.ng/recruitment"
        )) is not None
    )


def test_manual_registration_deduplicates_and_validates_actor(db_session, staff):
    source = manual(db_session, staff)
    assert manual(db_session, staff).id == source.id
    staff.is_staff = False
    db_session.commit()
    with pytest.raises(registry.RecruitmentError, match="staff"):
        manual(db_session, staff)


@pytest.mark.parametrize("missing", list(registry.CHECKS))
def test_approval_requires_each_separate_check(db_session, staff, missing):
    source = manual(db_session, staff)
    checks = {
        key: {"note": "Checked", "url": "https://example.org"}
        for key in registry.CHECKS
        if key != missing
    }
    with pytest.raises(registry.RecruitmentError):
        approve(db_session, staff, source, checks=checks)
    assert source.verification_status == "pending"
    assert not registry.collection_authorized(source)


def test_approval_expiry_revocation_and_stale_decisions(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source)
    assert registry.collection_authorized(source)
    assert not registry.collection_authorized(source, at=registry.now() + timedelta(days=91))
    old_revision = source.revision
    registry.review_source(
        db_session, staff, source, revision=old_revision, action="revoke", note="Domain compromised"
    )
    with pytest.raises(registry.RecruitmentError, match="changed"):
        approve(db_session, staff, source, revision=old_revision)
    assert source.verification_status == "revoked"
    assert not registry.collection_authorized(source)
    registry.review_source(
        db_session, staff, source, revision=source.revision, action="reopen", note="New evidence"
    )
    assert source.verification_status == "pending"
    assert not registry.collection_authorized(source)
    assert db_session.scalar(select(func.count()).select_from(SourceEvent)) == 4


def test_organisation_corrections_invalidate_related_approvals(db_session, staff):
    source = manual(db_session, staff)
    other = manual(db_session, staff, source_url="https://lshsc.ng/jobs")
    approve(db_session, staff, source)
    approve(db_session, staff, other)
    registry.update_organization(
        db_session,
        staff,
        source,
        revision=source.revision,
        name="Corrected name",
        category="health_commission",
        country_code="NG",
        location="Lagos",
    )
    db_session.expire_all()
    assert source.organization.name == "Corrected name"
    assert source.verification_status == other.verification_status == "pending"


def test_redirect_and_canonical_never_replace_user_url_and_new_domain_reopens(db_session, staff):
    source = manual(db_session, staff)
    approve(db_session, staff, source)
    worker.enqueue_due(db_session)
    worker.run_next(
        db_session,
        executor=lambda *_: observation(
            "https://different.example.org/recruitment",
            canonical_hint="https://canonical.example.org",
        ),
    )
    db_session.refresh(source)
    assert source.original_url == "https://lshsc.ng/recruitment"
    assert source.observed_url == "https://different.example.org/recruitment"
    assert source.verification_status == "pending"
    assert not registry.collection_authorized(source)


@pytest.mark.parametrize(
    "outcome", ["timeout", "access_blocked", "tls_error", "policy_blocked", "http_error"]
)
def test_access_failures_preserve_trust_and_do_not_publish_jobs(db_session, staff, outcome):
    source = manual(db_session, staff)
    approve(db_session, staff, source)
    worker.enqueue_due(db_session)
    task = worker.run_next(
        db_session,
        executor=lambda *_: {
            "ok": False,
            "outcome": outcome,
            "message": "Access failed",
            "retryable": True,
        },
    )
    db_session.refresh(source)
    assert task.status == "queued" and task.attempts == 1
    assert source.verification_status == "approved" and source.health_status == outcome
    assert source.failure_count == 1 and source.last_success_at is None
    assert source.last_vacancy_discovery_at is None
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize("action", ["pause", "revoke", "reject"])
def test_queued_source_changes_cancel_without_network(db_session, staff, action):
    source = manual(db_session, staff)
    worker.enqueue_due(db_session)
    registry.review_source(
        db_session, staff, source, revision=source.revision, action=action, note="Stop"
    )
    calls = []
    task = worker.run_next(db_session, executor=lambda *_: calls.append(True))
    assert task.status == "cancelled" and calls == []


def test_review_during_fetch_cancels_stale_result(db_session, staff):
    source = manual(db_session, staff)
    worker.enqueue_due(db_session)

    def execute(*_):
        registry.review_source(
            db_session, staff, source, revision=source.revision, action="pause", note="Hold"
        )
        return observation()

    task = worker.run_next(db_session, executor=execute)
    db_session.refresh(source)
    assert task.status == "cancelled"
    assert source.last_success_at is None and source.automation_status == "paused"


def test_lease_recovery_fences_old_worker_and_allows_only_one_network_task(db_session, staff):
    source = manual(db_session, staff)
    manual(db_session, staff, source_url="https://lshsc.ng/jobs")
    worker.enqueue_due(db_session)
    first = worker.claim_next(db_session)
    old_token = first.lease_token
    assert worker.claim_next(db_session) is None
    first.lease_until = registry.now() - timedelta(seconds=1)
    db_session.commit()
    second = worker.claim_next(db_session)
    assert second is not None
    assert not worker.apply_result(
        db_session, first.id, old_token, {"revision": source.revision}, observation()
    )
    assert source.last_success_at is None
    assert db_session.scalar(select(func.count()).select_from(SourceEvent)) == 2


def test_malformed_worker_result_rolls_back_partial_observations(db_session, staff):
    source = manual(db_session, staff)
    worker.enqueue_due(db_session)
    task = worker.run_next(db_session, executor=lambda *_: observation("http://127.0.0.1/private"))
    db_session.refresh(source)
    assert task.outcome == "processing_error"
    assert source.last_success_at is None and source.observed_url == ""
    assert source.verification_status == "pending"


def test_disabled_schedule_does_not_call_provider(db_session, staff):
    schedule = registry.add_schedule(
        db_session, staff, name="NG", provider="ror", country_code="NG", query="", interval_hours=24
    )
    worker.enqueue_due(db_session)
    registry.set_schedule_enabled(db_session, staff, schedule, enabled=False)
    calls = []
    task = worker.run_next(db_session, executor=lambda *_: calls.append(True))
    assert task.status == "cancelled" and not calls


def test_daily_limit_and_persistent_network_cooldown(db_session, staff, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 60)
    manual(db_session, staff)
    manual(db_session, staff, source_url="https://lshsc.ng/jobs")
    worker.enqueue_due(db_session)
    task = worker.run_next(db_session, executor=lambda *_: observation())
    assert worker.claim_next(db_session) is None
    task.network_pause_until = registry.now() - timedelta(seconds=1)
    db_session.commit()
    monkeypatch.setattr(settings, "recruitment_daily_task_limit", 1)
    assert worker.claim_next(db_session) is None


def test_rate_limit_pauses_all_network_work(db_session, staff):
    manual(db_session, staff)
    manual(db_session, staff, source_url="https://lshsc.ng/jobs")
    worker.enqueue_due(db_session)
    task = worker.run_next(
        db_session,
        executor=lambda *_: {
            "ok": False,
            "outcome": "rate_limited",
            "retryable": True,
            "retry_after": 3600,
        },
    )
    assert registry.utc(task.network_pause_until) > registry.now() + timedelta(minutes=59)
    assert worker.claim_next(db_session) is None


def test_search_needs_credentials_and_result_storage_permission(db_session, staff, monkeypatch):
    monkeypatch.setattr(settings, "recruitment_search_key", "test-private-key")
    monkeypatch.setattr(settings, "recruitment_search_permission_reference", "")
    with pytest.raises(registry.RecruitmentError, match="permission"):
        registry.add_schedule(
            db_session,
            staff,
            name="Search",
            provider="brave",
            country_code="NG",
            query="nurse jobs",
            interval_hours=24,
        )
    fixture = DirectoryFixture()
    result = execute_discovery(
        "brave", {"query": "nurse jobs"}, fetcher=fixture, search_key="test-private-key"
    )
    assert result["outcome"] == "configuration_needed" and not fixture.requests
    assert "test-private-key" not in str(result)
    assert "Abia" in search_query(
        {"query": "{region} {category} {country}", "country_code": "NG",
         "page": len(DISCOVERY_CATEGORIES) + 1}
    )
    assert "health service commission" in search_query(
        {"query": "{category}", "country_code": "NZ", "page": 2}
    )


def test_real_spawned_adapter_requires_no_network_when_disabled():
    result = worker.isolated_execute("brave", {"query": "nursing"})
    assert result["ok"] is False
    assert result["outcome"] == "configuration_needed"


def test_admin_pages_are_private_csrf_protected_and_escape_external_names(client, db_session):
    assert client.get("/recruitment", follow_redirects=False).status_code in {303, 401}
    register_and_sign_in(client)
    assert client.get("/recruitment").status_code == 403
    user = db_session.scalar(select(User))
    user.is_staff = True
    db_session.commit()
    page = client.get("/recruitment")
    assert page.status_code == 200
    data = {
        "name": '<script>alert("source")</script>',
        "category": "healthcare",
        "country_code": "NG",
        "website_url": "https://example.org",
        "source_url": "https://example.org/jobs",
    }
    assert client.post("/recruitment/sources", data=data).status_code == 400
    data["csrf_token"] = csrf_from(page)
    response = client.post("/recruitment/sources", data=data)
    assert response.status_code == 200
    assert '<script>alert("source")</script>' not in response.text
    assert "&lt;script&gt;" in response.text
    source = db_session.scalar(select(RecruitmentSource))
    path = f"/recruitment/sources/{source.id}/review"
    assert client.post(path, data={"revision": 0, "action": "approve"}).status_code == 400
    invalid = client.post(
        path,
        data={
            "csrf_token": csrf_from(response),
            "revision": source.revision,
            "action": "approve",
            "expires_at": "bad date",
        },
    )
    assert invalid.status_code == 400
    assert source.verification_status == "pending"
    user.is_staff = False
    db_session.commit()
    assert client.get(f"/recruitment/sources/{source.id}").status_code == 403
    assert (
        client.post(
            path,
            data={
                "csrf_token": data["csrf_token"],
                "revision": 0,
                "action": "reopen",
                "note": "Try",
            },
        ).status_code
        == 403
    )


def test_hard_process_deadline_stops_unfinished_check(monkeypatch):
    monkeypatch.setattr(worker, "TASK_SECONDS", 0.001)
    result = worker.isolated_execute("brave", {"query": "nursing"})
    assert result["outcome"] == "timeout" and result["retryable"]


def test_successful_http_approval_and_schedule_management(client, db_session):
    register_and_sign_in(client)
    user = db_session.scalar(select(User))
    user.is_staff = True
    db_session.commit()
    source = manual(db_session, user)
    page = client.get(f"/recruitment/sources/{source.id}")
    payload = {
        "csrf_token": csrf_from(page),
        "revision": source.revision,
        "action": "approve",
        "method": "html",
        "note": "Checked official records",
        "reuse_basis": "legal_basis",
        "reuse_url_prefix": source.original_url,
        **{right: "true" for right in registry.REUSE_RIGHTS},
        "expires_at": (registry.now() + timedelta(days=30)).date().isoformat(),
    }
    for key in registry.CHECKS:
        payload[f"{key}_note"] = "Evidence for " + key
        payload[f"{key}_url"] = "https://example.org/evidence"
    response = client.post(f"/recruitment/sources/{source.id}/review", data=payload)
    assert response.status_code == 200
    db_session.refresh(source)
    assert registry.collection_authorized(source)
    payload["note"] = "Stale form cannot override decision"
    assert client.post(f"/recruitment/sources/{source.id}/review", data=payload).status_code == 400
    response = client.post(
        "/recruitment/schedules",
        data={
            "csrf_token": csrf_from(page),
            "name": "Worldwide institutions",
            "provider": "ror",
            "country_code": "",
            "interval_hours": 24,
        },
    )
    assert response.status_code == 200
    schedule = db_session.scalar(select(DiscoverySchedule))
    assert schedule.enabled
    response = client.post(
        f"/recruitment/schedules/{schedule.id}",
        data={"csrf_token": csrf_from(page), "enabled": "false"},
    )
    db_session.refresh(schedule)
    assert response.status_code == 200 and not schedule.enabled
