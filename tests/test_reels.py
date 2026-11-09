"""Reels publishing, privacy, real video processing and shared community rules."""

import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.community_storage import community_media_path
from app.core.config import settings
from app.models.community import CommunityMedia, ContentReport, ContentStatus, Follow
from app.models.reels import Reel, ReelSave
from app.services import reel_worker
from app.services.accounts import delete_account
from app.services.community import CommunityError, moderate_report, reconcile_community_media
from app.services.reels import clean_captions, list_reels, remove_reel
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_community import (
    AUTHOR_PHONE,
    PASSWORD,
    READER_PHONE,
    create_topic,
    mp4,
    set_name,
    user_by_phone,
)


@pytest.fixture(autouse=True)
def media_dir(tmp_path, monkeypatch):
    path = tmp_path / "media"
    monkeypatch.setattr(settings, "community_media_dir", str(path))
    monkeypatch.setattr(settings, "community_malware_scan_mode", "disabled")
    return path


@pytest.fixture(scope="session")
def real_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("reel-video") / "clip.mp4"
    subprocess.run([
        reel_worker.ffmpeg_binary(), "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=360x640:rate=24", "-f", "lavfi", "-i", "sine=frequency=500",
        "-t", "1.5", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(path),
    ], check=True, timeout=30, capture_output=True)
    return path.read_bytes()


@pytest.fixture
def author(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client, "Reels Creator")
    topic = create_topic(db_session)
    return user_by_phone(db_session, AUTHOR_PHONE), topic


def upload(client, topic, data, **values):
    page = client.get("/reels/new")
    payload = {
        "csrf_token": csrf_from(page), "topic_id": str(topic.id),
        "upload_key": str(uuid.uuid4()), "body": "A useful Nigerian internship guide",
        "category": "opportunities", "audience": "nigeria", "consent": "yes", **values,
    }
    return client.post("/reels", data=payload,
                       files={"video": ("clip.mp4", data, "video/mp4")},
                       headers={"X-Reel-Upload": "1"}, follow_redirects=False)


def latest(db):
    return db.scalar(select(Reel).order_by(Reel.created_at.desc(), Reel.post_id.desc()))


def ready(client, db, topic, data):
    response = upload(client, topic, data)
    assert response.status_code == 201, response.text
    reel = latest(db)
    assert reel_worker.run_next(db) == (str(reel.post_id), "ready")
    db.expire_all()
    return db.get(Reel, reel.post_id)


def test_public_empty_feed_and_auth_boundaries(client):
    assert "Every useful story starts" in client.get("/reels").text
    for path in ("/reels/new", "/reels/mine", "/reels?view=saved", "/reels?view=following"):
        assert client.get(path, follow_redirects=False).headers["location"] == "/auth/login"
    assert client.get("/reels/not-a-uuid").status_code == 404


def test_first_reel_uses_account_name_without_extra_fields(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    user = user_by_phone(db_session, AUTHOR_PHONE)
    user.full_name = "Ada Okafor"
    db_session.commit()
    topic = create_topic(db_session)
    page = client.get("/reels/new")
    assert "Posting as <strong>Ada Okafor</strong>" in page.text
    assert 'name="community_name"' not in page.text
    assert 'name="job_link"' not in page.text
    assert not user.community_name  # Viewing the form does not change identity.
    response = upload(client, topic, mp4(2), community_name="A forged name",
                      job_link="https://example.org/unused")
    assert response.status_code == 201, response.text
    db_session.refresh(user)
    reel = latest(db_session)
    assert user.community_name == "Ada Okafor"
    assert user.community_name_locked and reel.job_id is None
    assert reel.post.author.community_name == "Ada Okafor"


def test_existing_public_identity_is_preserved(client, db_session, author):
    user, topic = author
    user.full_name = "Different account name"
    db_session.commit()
    response = upload(client, topic, mp4(2))
    assert response.status_code == 201
    assert latest(db_session).post.author.community_name == "Reels Creator"


def test_members_with_same_account_name_can_both_upload(client, db_session, author):
    client.cookies.clear()
    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    reader = user_by_phone(db_session, READER_PHONE)
    reader.full_name = author[0].community_name
    db_session.commit()
    response = upload(client, author[1], mp4(2))
    assert response.status_code == 201, response.text
    db_session.refresh(reader)
    assert reader.community_name.startswith("Reels Creator · ")
    assert reader.community_name_key != author[0].community_name_key


def test_legacy_unnamed_account_does_not_expose_contact_details(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    user = user_by_phone(db_session, AUTHOR_PHONE)
    user.email = "private@example.org"
    db_session.commit()
    response = upload(client, create_topic(db_session), mp4(2))
    assert response.status_code == 201
    db_session.refresh(user)
    assert user.community_name == "Nurse.ng member"


def test_upload_is_private_and_repeated_request_does_not_duplicate(
    client, db_session, author, real_video,
):
    user, topic = author
    key = str(uuid.uuid4())
    first = upload(client, topic, real_video, upload_key=key)
    assert first.status_code == 201
    reel = latest(db_session)
    assert reel.state == "queued" and reel.post.status == ContentStatus.PROCESSING
    source = reel.post.media[0]
    assert client.get(f"/community/media/{source.id}").status_code == 404
    assert client.get(f"/posts/{reel.post_id}").status_code == 404
    assert client.get(f"/reels/{reel.post_id}").status_code == 404
    assert "A useful Nigerian internship guide" not in client.get("/feed").text
    assert "Making your reel ready" in client.get(first.json()["redirect"]).text
    again = upload(client, topic, real_video, upload_key=key)
    assert again.json()["redirect"] == first.json()["redirect"]
    assert db_session.scalar(select(func.count()).select_from(Reel)) == 1
    assert len(list(Path(settings.community_media_dir).iterdir())) == 1
    client.cookies.clear()
    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    assert client.get(first.json()["redirect"]).status_code == 404
    assert client.post(f"/reels/{reel.post_id}/remove", data={
        "csrf_token": csrf_from(client.get("/reels")),
    }).status_code == 404


def test_real_worker_publishes_compatible_renditions_and_removes_original(
    client, db_session, author, real_video,
):
    user, topic = author
    assert upload(client, topic, real_video).status_code == 201
    reel = latest(db_session)
    original = reel.post.media[0].storage_name
    assert reel_worker.run_next(db_session) == (str(reel.post_id), "ready")
    db_session.expire_all()
    reel = db_session.get(Reel, reel.post_id)
    assert not community_media_path(original).exists()
    media = {m.kind: m for m in reel.post.media}
    assert set(media) == {"video", "reel_low", "reel_poster"}
    assert user.community_storage_bytes == sum(m.size_bytes for m in media.values())
    assert client.get(f"/reels/{reel.post_id}").status_code == 200
    assert client.get("/reels").status_code == 200
    assert "Reels Creator" in client.get("/reels").text
    for kind in ("video", "reel_low"):
        file = community_media_path(media[kind].storage_name)
        decoded = subprocess.run([
            reel_worker.ffmpeg_binary(), "-v", "error", "-i", str(file),
            "-f", "null", "-",
        ], capture_output=True, timeout=30)
        assert decoded.returncode == 0, decoded.stderr.decode()
        response = client.get(f"/community/media/{media[kind].id}",
                              headers={"Range": "bytes=0-127"})
        assert response.status_code == 206 and len(response.content) == 128
        assert response.headers["cache-control"] == "no-store"
    assert client.get(f"/community/media/{media['reel_poster'].id}").headers[
        "content-type"
    ] == "image/jpeg"
    assert reel_worker.run_next(db_session) is None


@pytest.mark.parametrize("values", [
    {"consent": ""}, {"category": "invented"}, {"audience": "invented"},
    {"body": ""}, {"cover_seconds": "8"}, {"upload_key": "invalid"},
])
def test_invalid_upload_does_not_publish_or_retain_files(
    client, db_session, author, real_video, media_dir, values,
):
    response = upload(client, author[1], real_video, **values)
    assert response.status_code == 400, response.text
    assert not list(db_session.scalars(select(Reel)))
    assert not list(media_dir.glob("*"))


def test_csrf_and_upload_rate_limit(client, db_session, author, real_video):
    topic = author[1]
    assert upload(client, topic, real_video, csrf_token="invalid").status_code == 400
    from app.web.community_routes import _post_limiter

    for _ in range(_post_limiter.limit):
        _post_limiter.record(str(author[0].id))
    response = upload(client, topic, real_video)
    assert response.status_code == 429 and "retry-after" in response.headers


def test_fake_mp4_fails_in_decoder_and_stays_private(client, db_session, author):
    assert upload(client, author[1], mp4(2)).status_code == 201
    reel = latest(db_session)
    assert reel_worker.run_next(db_session) == (str(reel.post_id), "failed")
    db_session.refresh(reel)
    assert reel.state == "failed" and "decoded" in reel.error
    assert client.get(f"/reels/{reel.post_id}").status_code == 404
    assert client.get(f"/community/media/{reel.post.media[0].id}").status_code == 404
    response = client.get(f"/reels/{reel.post_id}/status")
    assert "Your video needs attention" in response.text
    token = csrf_from(response)
    assert client.post(f"/reels/{reel.post_id}/retry", data={"csrf_token": token},
                       follow_redirects=False).status_code == 303
    db_session.refresh(reel)
    assert reel.state == "queued"


def test_leases_exclude_other_worker_and_recover_after_crash(
    client, db_session, author, real_video,
):
    upload(client, author[1], real_video)
    first = reel_worker.claim_next(db_session)
    assert first and reel_worker.claim_next(db_session) is None
    reel = latest(db_session)
    reel.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    second = reel_worker.claim_next(db_session)
    assert first[0] == second[0] and first[1] != second[1]
    reel.attempts = 3
    reel.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert reel_worker.claim_next(db_session) is None
    db_session.refresh(reel)
    assert reel.state == "failed"


def test_reconciliation_keeps_pending_sources(client, db_session, author, real_video):
    upload(client, author[1], real_video)
    reel = latest(db_session)
    source = reel.post.media[0].storage_name
    result = reconcile_community_media(db_session)
    assert result["removed_files"] == 0 and result["corrected_accounts"] == 0
    assert community_media_path(source).exists()


def test_creator_removal_during_processing_cannot_be_undone(
    client, db_session, author, real_video, monkeypatch, media_dir,
):
    upload(client, author[1], real_video)
    reel = latest(db_session)
    original = reel_worker.transcode

    def remove_during_decode(*args):
        output = original(*args)
        remove_reel(db_session, reel, author[0])
        return output

    monkeypatch.setattr(reel_worker, "transcode", remove_during_decode)
    assert reel_worker.run_next(db_session) == (str(reel.post_id), "cancelled")
    db_session.expire_all()
    assert reel.post.status == ContentStatus.REMOVED
    assert not list(media_dir.glob("*"))


def test_nigerian_priority_filters_and_private_saved_following_views(
    client, db_session, author, real_video,
):
    nigerian = ready(client, db_session, author[1], real_video)
    global_reel = ready(client, db_session, author[1], real_video)
    global_reel.audience = "global"
    global_reel.category = "learning"
    db_session.commit()
    assert list_reels(db_session, user=None, view="discover")[0].post_id == nigerian.post_id
    assert list_reels(db_session, user=None, view="discover", category="learning") == [global_reel]
    client.cookies.clear()
    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    reader = user_by_phone(db_session, READER_PHONE)
    token = csrf_from(client.get("/reels"))
    for _ in range(2):
        assert client.post(f"/reels/{nigerian.post_id}/save", data={
            "csrf_token": token, "saved": "yes",
        }, headers={"X-Reel-Action": "1"}).json()["saved"] is True
        assert client.post(f"/reels/{nigerian.post_id}/follow", data={
            "csrf_token": token, "following": "yes",
        }, headers={"X-Reel-Action": "1"}).json()["following"] is True
    assert db_session.scalar(select(func.count()).select_from(ReelSave)) == 1
    assert db_session.scalar(select(func.count()).select_from(Follow)) == 1
    assert list_reels(db_session, user=reader, view="saved") == [nigerian]
    assert len(list_reels(db_session, user=reader, view="following")) == 2
    assert not list_reels(db_session, user=author[0], view="saved")
    assert client.get("/reels?view=following").status_code == 200


def test_comments_and_reports_use_existing_conversation_and_moderation(
    client, db_session, author, real_video, media_dir,
):
    reel = ready(client, db_session, author[1], real_video)
    token = csrf_from(client.get("/reels"))
    assert client.post(f"/reels/{reel.post_id}/comments", data={
        "csrf_token": token, "body": "Where can I apply?",
    }, headers={"X-Reel-Action": "1"}).status_code == 200
    assert "Where can I apply?" in client.get(f"/posts/{reel.post_id}").text
    assert "Where can I apply?" in client.get(f"/reels/{reel.post_id}/comments").text
    client.cookies.clear()
    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    token = csrf_from(client.get("/reels"))
    assert client.post(f"/reels/{reel.post_id}/report", data={
        "csrf_token": token, "reason": "privacy", "details": "Private record visible",
    }, headers={"X-Reel-Action": "1"}).status_code == 200
    author[0].is_staff = True
    db_session.commit()
    report = db_session.scalar(select(ContentReport))
    moderate_report(db_session, author[0], report, action="remove", note="Contains private data")
    assert client.get(f"/reels/{reel.post_id}").status_code == 404
    assert not list(media_dir.glob("*"))


def test_account_deletion_removes_all_reel_files_and_saves(
    client, db_session, author, real_video, media_dir,
):
    ready(client, db_session, author[1], real_video)
    upload(client, author[1], real_video)
    assert len(list(media_dir.glob("*"))) == 4
    delete_account(db_session, author[0], password=PASSWORD)
    assert not list(media_dir.glob("*"))
    assert db_session.scalar(select(func.count()).select_from(Reel)) == 0
    assert db_session.scalar(select(func.count()).select_from(CommunityMedia)) == 0


@pytest.mark.parametrize("value", [
    b"garbage", b"WEBVTT\n\nSTYLE\n::cue {color:red}",
    b"WEBVTT\n\n00:00:03.000 --> 00:00:01.000\nBad time",
    b"WEBVTT\n\n00:00:00.000 --> 00:00:08.000\nToo long",
])
def test_reject_invalid_captions(value):
    with pytest.raises(CommunityError):
        clean_captions(value, 3)


def test_caption_markup_is_plain_text():
    value = clean_captions(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<script>x</script>", 2)
    assert "<script>" not in value and "&lt;script&gt;" in value
