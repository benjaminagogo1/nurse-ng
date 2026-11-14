"""Staff source approval must reach factual publication through the actual worker."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.recruitment import SourceEvent
from app.models.user import User
from app.models.vacancies import VacancyRecord, VacancySnapshot
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.jobs import list_open_jobs
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancies import collector_authorized
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_automatic_activation import check, staff
from tests.test_factual_opportunities import PROSE, fixture


def activate(db, actor, item, **overrides):
    registry.review_source(
        db, actor, item,
        **{
            "revision": item.revision,
            "action": "approve_index",
            "note": "Selected by the operator for factual job collection.",
            "expires_at": registry.now() + timedelta(days=90),
            **overrides,
        },
    )


def test_staff_approval_collects_publishes_and_refreshes_facts(db_session, monkeypatch, client):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session, host="https://hospital.example.ng/")
    actor = staff(db_session)
    activate(db_session, actor, item)
    assert collector_authorized(item)
    assert item.approval_mode == "staff" and item.last_verified_at is None
    task = check(db_session, item, fetched)
    assert task.status == "completed", task.message
    jobs = list_open_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0].normalized_data["announcement_url"] == target
    assert client.get(f"/jobs/{jobs[0].id}").status_code == 200
    assert not item.allow_snapshot_retention and not item.allow_republication
    for snapshot in db_session.scalars(select(VacancySnapshot)):
        assert PROSE.encode() not in snapshot.body
        assert isinstance(json.loads(snapshot.body)["records"], list)
    previous = jobs[0].confirmed_at
    check(db_session, item, fetched)
    db_session.refresh(jobs[0])
    assert jobs[0].confirmed_at >= previous and len(list_open_jobs(db_session)) == 1
    event = db_session.scalar(select(SourceEvent).where(SourceEvent.kind == "approve_index"))
    assert event.actor_id == actor.id and event.details["mode"] == "factual_index"
    with pytest.raises(registry.RecruitmentError, match="changed"):
        activate(db_session, actor, item, revision=item.revision - 1)


@pytest.mark.parametrize("control", ["revoke", "pause", "expiry", "scope", "permission"])
def test_staff_collection_and_public_listing_stop_when_control_changes(
    db_session, monkeypatch, control
):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, _ = fixture(db_session, host="https://hospital.example.ng/")
    actor = staff(db_session)
    activate(db_session, actor, item)
    check(db_session, item, fetched)
    assert len(list_open_jobs(db_session)) == 1
    if control in {"revoke", "pause"}:
        registry.review_source(
            db_session, actor, item, revision=item.revision,
            action=control, note="Stop this source.",
        )
    elif control == "expiry":
        item.approval_expires_at = registry.now() - timedelta(seconds=1)
    elif control == "scope":
        item.reuse_url_prefix = "https://other.example.ng/"
    else:
        item.allow_collection = False
    db_session.commit()
    assert not collector_authorized(item)
    assert list_open_jobs(db_session) == []


def test_http_source_and_www_redirect_preserve_original_url(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    host = "https://www.hospital.example.ng/"
    item, fetched, _ = fixture(db_session, host=host)
    item.original_url = "http://hospital.example.ng/"
    db_session.commit()
    activate(db_session, staff(db_session), item)
    fetched.responses["https://hospital.example.ng/robots.txt"] = FetchedPage("", 404, "", b"")
    fetched.responses["https://hospital.example.ng/"] = FetchedPage(host, 301, "", b"")
    task = check(db_session, item, fetched)
    assert task.status == "completed", task.message
    assert item.original_url == "http://hospital.example.ng/"
    assert item.observed_url == host and item.reuse_url_prefix == host
    assert item.verification_status == "approved" and collector_authorized(item)
    assert len(list_open_jobs(db_session)) == 1


def test_another_publisher_redirect_is_blocked_before_destination_fetch(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    host = "https://hospital.example.ng/"
    item, fetched, _ = fixture(db_session, host=host)
    activate(db_session, staff(db_session), item)
    fetched.responses[host] = FetchedPage("https://other.example.ng/jobs", 302, "", b"")
    task = check(db_session, item, fetched)
    assert task.outcome == "scope_blocked"
    assert not any(url.startswith("https://other.example.ng") for url, _ in fetched.calls)
    assert list_open_jobs(db_session) == []


def test_source_and_job_country_can_remain_unknown(db_session, monkeypatch):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    item, fetched, target = fixture(db_session, host="https://hospital.example.ng/")
    item.organization.country_code = ""
    db_session.commit()
    activate(db_session, staff(db_session), item)
    fetched.responses[target].body = fetched.responses[target].body.replace(
        b"Nigeria", b"elsewhere"
    )
    check(db_session, item, fetched)
    assert collector_authorized(item)
    assert len(list_open_jobs(db_session)) == 1
    record = db_session.scalar(select(VacancyRecord))
    assert record.normalized['country'] == ''
    assert not any(issue.startswith('country:') for issue in record.issues)


def test_combined_approval_is_staff_only_and_has_csrf_and_revision_checks(client, db_session):
    register_and_sign_in(client)
    actor = db_session.scalar(select(User))
    actor.is_staff = True
    db_session.commit()
    item, _, _ = fixture(db_session, host="https://hospital.example.ng/")
    path = f"/recruitment/sources/{item.id}/review"
    page = client.get(f"/recruitment/sources/{item.id}")
    assert "Approve and start collection" in page.text
    data = {
        "revision": item.revision, "action": "approve_index", "note": "Approved by the operator.",
        "expires_at": (registry.now() + timedelta(days=90)).date().isoformat(),
    }
    assert client.post(path, data=data).status_code == 400
    data["csrf_token"] = csrf_from(page)
    assert client.post(path, data=data).status_code == 200
    assert collector_authorized(item)
    assert client.post(path, data=data).status_code == 400
    actor.is_staff = False
    db_session.commit()
    data["revision"] = item.revision
    assert client.post(path, data=data).status_code == 403
