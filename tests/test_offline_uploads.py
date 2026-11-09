# ruff: noqa: F811
"""Interrupted and repeated uploads retain validation, ownership and publication integrity."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.offline_upload import OfflineUpload
from app.models.reels import Reel
from app.services import offline_uploads, reel_worker
from tests.test_community import create_topic, sign_in
from tests.test_offline import headers, member, operation
from tests.test_reels import real_video  # noqa: F401


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "community_media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "community_malware_scan_mode", "disabled")


def begin(client, identifier, size, auth=None):
    return client.post(
        f"/offline/uploads/{identifier}", json={"size": size}, headers=auth or headers(client)
    )


def chunk(client, identifier, offset, data, auth=None):
    return client.put(
        f"/offline/uploads/{identifier}?offset={offset}",
        content=data,
        headers=auth or headers(client),
    )


def test_resume_duplicate_chunks_and_single_validated_publication(client, db_session, real_video):
    user = member(db_session)
    topic = create_topic(db_session)
    sign_in(client, user.phone)
    # A valid MP4 free box creates several transport chunks without changing video content.
    padding = b"\x00" * (2 * offline_uploads.CHUNK)
    video = real_video + (len(padding) + 8).to_bytes(4, "big") + b"free" + padding
    identifier = uuid4()
    assert begin(client, identifier, len(video)).json()["received"] == 0
    first = video[: offline_uploads.CHUNK]
    assert chunk(client, identifier, 0, first).json()["received"] == len(first)
    assert chunk(client, identifier, 0, first).json()["received"] == len(first)
    assert chunk(client, identifier, 0, b"x" * len(first)).status_code == 409
    assert chunk(client, identifier, 2 * len(first), video[2 * len(first) :]).status_code == 409
    resumed = begin(client, identifier, len(video)).json()
    assert resumed["received"] == len(first)
    assert chunk(client, identifier, len(first), b"partial").status_code == 400
    for offset in range(resumed["received"], len(video), offline_uploads.CHUNK):
        response = chunk(client, identifier, offset, video[offset : offset + offline_uploads.CHUNK])
        assert response.status_code == 200, response.text
    payload = {
        "file_id": str(identifier),
        "file_size": len(video),
        "upload_key": str(uuid4()),
        "topic_id": str(topic.id),
        "body": "Prepared offline",
        "category": "career",
        "audience": "nigeria",
        "cover_seconds": 0,
        "captions": "",
        "consent": True,
    }
    operation_id = uuid4()
    response = operation(client, "reel", payload, operation_id)
    assert response.status_code == 200, response.text
    assert "awaits processing" in response.json()["result"]["message"]
    assert begin(client, identifier, len(video)).json()["complete"] is True
    assert operation(client, "reel", payload, operation_id).json() == response.json()
    assert operation(client, "reel", payload).json() == response.json()
    assert (
        operation(client, "reel", {**payload, "body": "Different publication"}).status_code == 409
    )
    assert db_session.scalar(select(func.count()).select_from(Reel)) == 1
    assert list(offline_uploads.directory(user.id, identifier).iterdir())[0].name == ".lock"
    assert reel_worker.run_next(db_session)[1] == "ready"
    db_session.expire_all()
    assert db_session.get(Reel, UUID(response.json()["result"]["id"])).state == "ready"


def test_staging_authentication_scope_size_limits_and_expiry(client, db_session):
    user = member(db_session)
    identifier = uuid4()
    assert client.post(f"/offline/uploads/{identifier}", json={"size": 12}).status_code == 401
    sign_in(client, user.phone)
    auth = headers(client)
    assert begin(client, identifier, 12, {**auth, "X-CSRF-Token": "bad"}).status_code == 403
    assert begin(client, identifier, 12).status_code == 200
    assert begin(client, identifier, 13).status_code == 409
    assert begin(client, uuid4(), 101 * offline_uploads.CHUNK).status_code == 413
    assert chunk(client, identifier, 0, b"x" * (offline_uploads.CHUNK + 1)).status_code == 413
    assert begin(client, uuid4(), 1).status_code == 200
    assert begin(client, uuid4(), 1).status_code == 409
    row = db_session.get(OfflineUpload, (user.id, identifier))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert chunk(client, identifier, 0, b"123456789012").status_code == 410
    offline_uploads.cleanup(db_session)
    assert db_session.get(OfflineUpload, (user.id, identifier)) is None
    other = member(db_session, "3")
    sign_in(client, other.phone)
    assert chunk(client, identifier, 0, b"123456789012").status_code == 404


def test_invalid_video_never_publishes_and_remains_recoverable(client, db_session):
    user = member(db_session)
    topic = create_topic(db_session)
    sign_in(client, user.phone)
    identifier = uuid4()
    body = b"not a video"
    assert begin(client, identifier, len(body)).status_code == 200
    assert chunk(client, identifier, 0, body).status_code == 200
    payload = {
        "file_id": str(identifier),
        "file_size": len(body),
        "upload_key": str(uuid4()),
        "topic_id": str(topic.id),
        "body": "Prepared offline",
        "category": "career",
        "audience": "nigeria",
        "cover_seconds": 0,
        "captions": "",
        "consent": True,
    }
    response = operation(client, "reel", payload)
    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Reel)) == 0
    assert begin(client, identifier, len(body)).json()["complete"] is False
    assert (offline_uploads.directory(user.id, identifier) / "0").exists()
    response = client.delete(f"/offline/uploads/{identifier}", headers=headers(client))
    assert response.json() == {"discarded": True}
    assert db_session.get(OfflineUpload, (user.id, identifier)) is None
