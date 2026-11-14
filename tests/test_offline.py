"""Offline shell privacy, synchronization integrity and current authorization."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.offline import OfflineOperation
from app.models.opportunities import SavedOpportunity
from app.models.profile import NurseProfile
from app.models.user import User
from app.services import offline
from app.services.auth import register_user
from app.services.jobs import create_job
from app.services.profiles import save_profile
from tests.helpers import approve_test_employer
from tests.test_community import sign_in


def test_shell_has_no_member_data_or_credentials(client, db_session):
    user = register_user(
        db_session,
        phone="+2348999888111",
        password="s3cret-pass",
        full_name="Private Offline Member",
    )
    sign_in(client, user.phone)
    response = client.get("/offline-shell")
    assert response.status_code == 200
    assert user.phone not in response.text and user.full_name not in response.text
    assert 'name="csrf_token"' not in response.text
    assert 'data-draft-scope=""' in response.text
    assert 'data-offline-session="unknown"' in response.text
    assert "js/community-drafts.js" not in response.text
    assert "public" in response.headers["cache-control"]
    assert "Offline &amp; sync" in client.get("/offline").text


def test_worker_and_manifest_are_served_at_the_site_root(client):
    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert worker.headers["cache-control"] == "no-cache"
    assert client.get("/manifest.webmanifest").json()["scope"] == "/"
    assert client.get("/offline/ping").headers["cache-control"] == "no-store"


def member(db, number="1", **kwargs):
    return register_user(
        db,
        phone="+234899988822" + number,
        password="s3cret-pass",
        full_name="Offline Member",
        **kwargs,
    )


def profile(db, user):
    return save_profile(
        db,
        user,
        display_name="Offline Member",
        professional_status="student",
        headline="Original headline",
        location="Lagos",
        bio="Original bio",
    )


def job(db):
    employer = member(db, "2", account_type="employer")
    approve_test_employer(db, employer, "Example Hospital")
    return create_job(
        db,
        employer,
        title="Nurse opportunity",
        organization="Example Hospital",
        location="Abuja",
        job_type="full_time",
        work_mode="on_site",
        salary_min="",
        salary_max="",
        description="An original description for this opportunity.",
    )


def headers(client):
    identity = client.get("/offline/session").json()
    return {"X-CSRF-Token": identity["csrf"], "X-Offline-Scope": identity["scope"]}


def operation(client, kind, payload, op_id=None, auth=None):
    return client.post(
        "/offline/operations",
        headers=auth or headers(client),
        json={
            "operation_id": str(op_id or uuid4()),
            "kind": kind,
            "payload": payload,
        },
    )


def test_profile_receipt_replays_lost_response_and_rejects_changed_payload(client, db_session):
    user = member(db_session)
    original = profile(db_session, user)
    sign_in(client, user.phone)
    base = client.get("/offline/data", params={"path": "/profile"}).json()["records"][0]["data"]
    payload = {"base": base, "values": {**base["values"], "headline": "Saved while offline"}}
    identifier = uuid4()
    first = operation(client, "profile", payload, identifier)
    assert first.status_code == 200, first.text
    assert operation(client, "profile", payload, identifier).json() == first.json()
    db_session.refresh(original)
    assert original.headline == "Saved while offline"
    assert db_session.scalar(select(func.count()).select_from(OfflineOperation)) == 1
    payload["values"]["headline"] = "Changed payload"
    assert operation(client, "profile", payload, identifier).status_code == 409
    receipt = db_session.get(OfflineOperation, (user.id, identifier))
    assert "Saved while offline" not in str(receipt.result)


def test_profile_merges_disjoint_edits_but_requires_review_of_conflicting_fields(
    client, db_session
):
    user = member(db_session)
    existing = profile(db_session, user)
    base = offline.profile_snapshot(db_session, user)
    existing.location = "Abuja"
    db_session.commit()
    sign_in(client, user.phone)
    payload = {"base": base, "values": {**base["values"], "headline": "Device A headline"}}
    assert operation(client, "profile", payload).status_code == 200
    db_session.refresh(existing)
    assert (existing.location, existing.headline) == ("Abuja", "Device A headline")
    payload["values"]["location"] = "Kano"
    response = operation(client, "profile", payload)
    assert response.status_code == 409
    assert response.json()["current"]["values"]["location"] == "Abuja"
    db_session.refresh(existing)
    assert existing.location == "Abuja"
    assert db_session.scalar(select(func.count()).select_from(OfflineOperation)) == 1


def test_sync_authorization_and_profile_field_allowlist(client, db_session):
    user = member(db_session)
    base = offline.profile_snapshot(db_session, user)
    payload = {"base": base, "values": base["values"]}
    assert client.get("/offline/data?path=/profile").status_code == 401
    sign_in(client, user.phone)
    auth = headers(client)
    assert (
        operation(client, "profile", payload, auth={**auth, "X-CSRF-Token": "bad"}).status_code
        == 403
    )
    assert (
        operation(client, "profile", payload, auth={**auth, "X-Offline-Scope": "bad"}).status_code
        == 401
    )
    payload["values"] = {**base["values"], "document_reviewed_name": "Forged verification"}
    assert operation(client, "profile", payload).status_code == 400
    assert db_session.scalar(select(func.count()).select_from(OfflineOperation)) == 0
    user.auth_version += 1
    db_session.commit()
    assert operation(client, "profile", payload, auth=auth).status_code == 401


def test_bookmark_retry_conflict_and_current_availability(client, db_session):
    user = member(db_session)
    listing = job(db_session)
    sign_in(client, user.phone)
    payload = {
        "job_id": str(listing.id),
        "base": {"saved": False, "remind": False},
        "saved": True,
        "remind": True,
    }
    identifier = uuid4()
    assert operation(client, "bookmark", payload, identifier).status_code == 200
    assert operation(client, "bookmark", payload, identifier).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(SavedOpportunity)) == 1
    assert operation(client, "bookmark", {**payload, "remind": False}).status_code == 409
    remove = {**payload, "base": {"saved": True, "remind": True}, "saved": False, "remind": False}
    assert operation(client, "bookmark", remove).status_code == 200
    listing.status = "closed"
    db_session.commit()
    assert operation(client, "bookmark", payload).status_code == 404


def test_data_is_explicit_private_and_bounded(client, db_session):
    user = member(db_session)
    own = profile(db_session, user)
    listing = job(db_session)
    sign_in(client, user.phone)
    response = client.get("/offline/data?path=/jobs")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["records"][0]["data"]["id"] == str(listing.id)
    assert client.get("/offline/data?path=/jobs&page=2").json()["records"] == []
    assert client.get(f"/offline/data?path=/p/{own.public_id}").status_code == 404
    for path in ["/profile/verification", "/settings", "https://example.com/", "/admin"]:
        assert client.get("/offline/data", params={"path": path}).status_code in {400, 404}
    data = client.get("/offline/data?path=/profile").json()
    assert "csrf" not in data and user.phone not in str(data)
    assert "document_reviewed_name" not in str(data)
    assert client.get("/offline/data?path=/notifications").status_code == 200
    assert client.get("/learning/materials/application-checklist").status_code == 200


def test_outer_transaction_rolls_back_service_internal_commit(db_session, monkeypatch):
    user = member(db_session)
    user_id = user.id

    def broken(work, actor, payload):
        actor.full_name = "This must roll back"
        work.commit()
        raise RuntimeError("failure before receipt commit")

    monkeypatch.setitem(offline.HANDLERS, "test", broken)
    with pytest.raises(RuntimeError):
        offline.synchronize(db_session, user, uuid4(), "test", {})
    db_session.expire_all()
    assert db_session.get(User, user_id).full_name == "Offline Member"
    assert db_session.scalar(select(func.count()).select_from(OfflineOperation)) == 0


def test_concurrent_duplicate_sync_with_real_sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = member(db)
        user_id = user.id
        profile(db, user)
        base = offline.profile_snapshot(db, user)
    identifier = uuid4()
    payload = {"base": base, "values": {**base["values"], "headline": "Only once"}}

    def send():
        with Session(engine) as db:
            return offline.synchronize(db, db.get(User, user_id), identifier, "profile", payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: send(), range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(OfflineOperation)) == 1
        assert db.scalar(select(NurseProfile.headline)) == "Only once"
    engine.dispose()
