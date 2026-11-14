"""Real authorization, shared counts and safe retries for video reactions."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models.community import CommunityMedia, CommunityPost
from app.models.engagement import PostLike
from app.models.reels import Reel
from app.services.auth import register_user
from tests.helpers import csrf_from, has_element
from tests.test_community import PASSWORD, create_topic, sign_in


@pytest.fixture
def video(db_session):
    author = register_user(db_session, phone="+2348000081001", password=PASSWORD)
    viewer = register_user(db_session, phone="+2348000081002", password=PASSWORD)
    topic = create_topic(db_session)
    post = CommunityPost(author_id=author.id, topic_id=topic.id, body="A public video",
                         external_video_url="https://www.youtube.com/watch?v=example")
    db_session.add(post)
    db_session.flush()
    for kind, content_type in (("video", "video/mp4"), ("reel_low", "video/mp4"),
                               ("reel_poster", "image/jpeg")):
        post.media.append(CommunityMedia(kind=kind, storage_name=uuid.uuid4().hex,
                                         content_type=content_type, size_bytes=1,
                                         duration_seconds=2 if kind != "reel_poster" else None))
    reel = Reel(post_id=post.id, upload_key=str(uuid.uuid4()), category="learning", state="ready")
    db_session.add(reel)
    db_session.commit()
    return post, reel, viewer


def react(client, post, liked="yes", channel="posts"):
    return client.post(f"/{channel}/{post.id}/like", headers={"X-Post-Like": "1"},
                       data={"csrf_token": csrf_from(client.get("/reels")), "liked": liked},
                       follow_redirects=False)


def test_likes_are_shared_between_reels_and_community_and_retries_are_idempotent(
    client, db_session, video,
):
    post, _, viewer = video
    sign_in(client, viewer.phone)
    assert react(client, post, channel="reels").json() == {"likes": 1, "liked": True}
    assert react(client, post).json() == {"likes": 1, "liked": True}
    assert db_session.scalar(select(func.count()).select_from(PostLike)) == 1
    for path in ("/feed", f"/posts/{post.id}", "/reels"):
        assert has_element(client.get(path), "button", **{"aria-pressed": "true"})
    other = register_user(db_session, phone="+2348000081003", password=PASSWORD)
    sign_in(client, other.phone)
    assert react(client, post).json() == {"likes": 2, "liked": True}
    assert react(client, post, "no").json() == {"likes": 1, "liked": False}
    assert react(client, post, "no").json() == {"likes": 1, "liked": False}
    assert db_session.scalar(select(PostLike.user_id)) == viewer.id


def test_guest_csrf_and_invalid_state_cannot_create_likes(client, db_session, video):
    post, _, viewer = video
    response = react(client, post)
    assert response.status_code == 303 and response.headers["location"] == "/auth/login"
    sign_in(client, viewer.phone)
    assert client.post(f"/posts/{post.id}/like", data={"liked": "yes"}).status_code == 400
    assert react(client, post, "toggle").status_code == 422
    assert db_session.scalar(select(func.count()).select_from(PostLike)) == 0


@pytest.mark.parametrize("state", ["queued", "processing", "failed", "removed"])
def test_unpublished_or_removed_video_cannot_be_liked(client, db_session, video, state):
    post, reel, viewer = video
    if state == "removed":
        post.status = "removed"
    else:
        reel.state = state
        post.status = "processing"
    db_session.commit()
    sign_in(client, viewer.phone)
    assert react(client, post).status_code == 404
    assert react(client, post, channel="reels").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(PostLike)) == 0


def test_regular_community_video_and_no_javascript_submission(client, db_session, video):
    post, reel, viewer = video
    db_session.delete(reel)
    db_session.commit()
    sign_in(client, viewer.phone)
    response = client.post(f"/posts/{post.id}/like", data={
        "csrf_token": csrf_from(client.get("/feed")), "liked": "yes",
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/posts/{post.id}"
    assert react(client, post, channel="reels").status_code == 404
    db_session.delete(viewer)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(PostLike)) == 0
