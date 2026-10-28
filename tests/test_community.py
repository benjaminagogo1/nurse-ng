"""Public community, media checks, relationships, reports, and moderation."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.community import (
    CommunityMedia,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    ConnectionStatus,
    ContentReport,
    ContentStatus,
    Follow,
    ReportStatus,
)
from app.models.profile import NurseProfile
from app.models.user import User
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_profile_pages import save_profile
from tests.test_profile_sharing import activate, save_sharing

AUTHOR_PHONE = "+2348011111111"
READER_PHONE = "+2348022222222"
STAFF_PHONE = "+2348033333333"
PASSWORD = "s3cret-pass"
JPEG = b"\xff\xd8\xff\xe0" + b"community-image" * 3


@pytest.fixture(autouse=True)
def community_media_dir(tmp_path, monkeypatch):
    directory = tmp_path / "community-media"
    monkeypatch.setattr(settings, "community_media_dir", str(directory))
    return directory


def mp4(seconds: int) -> bytes:
    def box(kind: bytes, payload: bytes) -> bytes:
        return (len(payload) + 8).to_bytes(4, "big") + kind + payload

    timescale = 1000
    movie_header = (
        b"\x00\x00\x00\x00"
        + (0).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
        + timescale.to_bytes(4, "big")
        + (seconds * timescale).to_bytes(4, "big")
    )
    return box(b"ftyp", b"isom\x00\x00\x00\x00isom") + box(
        b"moov", box(b"mvhd", movie_header)
    )


def user_by_phone(db_session, phone: str) -> User:
    user = db_session.scalar(select(User).where(User.phone == phone))
    assert user is not None
    return user


def create_topic(db_session, name: str = "General nursing") -> CommunityTopic:
    topic = CommunityTopic(
        name=name,
        slug=name.lower().replace(" ", "-"),
        description="Discuss nursing practice and professional life.",
        is_active=True,
    )
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    return topic


def set_name(client, name: str = "Ada Community"):
    token = csrf_from(client.get("/community/settings"))
    return client.post(
        "/community/settings",
        data={"csrf_token": token, "name": name},
        follow_redirects=False,
    )


def publish(
    client,
    topic: CommunityTopic,
    *,
    body: str = "What helped you during your first clinical placement?",
    external_video_url: str = "",
    files=None,
):
    token = csrf_from(client.get("/posts/new"))
    return client.post(
        "/posts",
        data={
            "csrf_token": token,
            "topic_id": str(topic.id),
            "body": body,
            "external_video_url": external_video_url,
        },
        files=files,
        follow_redirects=False,
    )


def sign_in(client, phone: str):
    client.cookies.clear()
    token = csrf_from(client.get("/auth/login"))
    response = client.post(
        "/auth/login",
        data={"csrf_token": token, "phone": phone, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def test_feed_topics_and_nurse_directory_are_public(client):
    assert client.get("/feed").status_code == 200
    assert client.get("/topics").status_code == 200
    assert client.get("/nurses").status_code == 200
    assert "Anyone can read" in client.get("/feed").text


def test_posting_needs_sign_in_and_a_public_community_name(client, db_session):
    topic = create_topic(db_session)
    anonymous = client.post("/posts", follow_redirects=False)
    assert anonymous.status_code == 303
    assert anonymous.headers["location"] == "/auth/login"

    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    response = publish(client, topic)

    assert response.status_code == 400
    assert "Choose a public community name" in response.text
    assert db_session.scalars(select(CommunityPost)).all() == []


def test_open_enrolment_can_post_without_a_profile_or_review(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    assert set_name(client).status_code == 303
    topic = create_topic(db_session)

    response = publish(client, topic)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/posts/")
    assert db_session.scalar(select(NurseProfile)) is None
    post = db_session.scalar(select(CommunityPost))
    assert post is not None
    assert post.status == ContentStatus.PUBLISHED


def test_one_post_appears_in_its_topic_and_public_feed(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)
    response = publish(client, topic, body="A shared conversation")
    post = db_session.scalar(select(CommunityPost))
    assert post is not None
    assert response.headers["location"] == f"/posts/{post.id}"

    client.cookies.clear()
    assert "A shared conversation" in client.get("/feed").text
    assert "A shared conversation" in client.get(f"/topics/{topic.slug}").text
    assert "A shared conversation" in client.get(f"/posts/{post.id}").text


def test_post_accepts_four_images_and_serves_them_from_checked_route(
    client, db_session, community_media_dir
):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)
    files = [("images", (f"photo-{number}.jpg", JPEG, "image/jpeg")) for number in range(4)]

    response = publish(client, topic, body="Four images", files=files)

    assert response.status_code == 303
    media = db_session.scalars(select(CommunityMedia)).all()
    assert len(media) == 4
    assert len(list(community_media_dir.glob("*"))) == 4
    image = client.get(f"/community/media/{media[0].id}")
    assert image.status_code == 200
    assert image.content == JPEG
    assert image.headers["x-content-type-options"] == "nosniff"


def test_fifth_image_is_rejected_without_storing_files(
    client, db_session, community_media_dir
):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)
    files = [("images", (f"photo-{number}.jpg", JPEG, "image/jpeg")) for number in range(5)]

    response = publish(client, topic, files=files)

    assert response.status_code == 400
    assert "at most 4 images" in response.text
    assert db_session.scalars(select(CommunityPost)).all() == []
    assert not community_media_dir.exists()


def test_three_minute_mp4_is_accepted_and_longer_video_is_rejected(
    client, db_session, community_media_dir
):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)

    accepted = publish(
        client,
        topic,
        body="Three minute video",
        files={"video": ("lesson.mp4", mp4(180), "video/mp4")},
    )
    assert accepted.status_code == 303
    video = db_session.scalar(select(CommunityMedia))
    assert video is not None
    assert video.duration_seconds == 180

    rejected = publish(
        client,
        topic,
        body="Too long",
        files={"video": ("long.mp4", mp4(181), "video/mp4")},
    )
    assert rejected.status_code == 400
    assert "at most 3 minutes" in rejected.text
    assert len(list(community_media_dir.glob("*"))) == 1


def test_external_video_link_must_be_http_or_https(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)

    bad = publish(client, topic, body="", external_video_url="javascript:alert(1)")
    assert bad.status_code == 400

    good = publish(
        client,
        topic,
        body="Useful procedure",
        external_video_url="https://video.example/nursing-procedure",
    )
    assert good.status_code == 303
    assert "https://video.example/nursing-procedure" in client.get("/feed").text


def test_registered_member_can_reply_but_anonymous_member_cannot(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)
    publish(client, topic)
    post = db_session.scalar(select(CommunityPost))
    assert post is not None

    client.cookies.clear()
    anonymous = client.post(f"/posts/{post.id}/replies", follow_redirects=False)
    assert anonymous.status_code == 303

    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    set_name(client, "Bola Reader")
    token = csrf_from(client.get(f"/posts/{post.id}"))
    response = client.post(
        f"/posts/{post.id}/replies",
        data={"csrf_token": token, "body": "Thank you for sharing this."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    reply = db_session.scalar(select(CommunityReply))
    assert reply is not None
    assert reply.status == ContentStatus.PUBLISHED


def test_member_report_and_staff_removal_hide_content(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    set_name(client)
    topic = create_topic(db_session)
    publish(client, topic, body="Content under review")
    post = db_session.scalar(select(CommunityPost))
    assert post is not None

    client.cookies.clear()
    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    token = csrf_from(client.get(f"/posts/{post.id}"))
    reported = client.post(
        f"/posts/{post.id}/report",
        data={"csrf_token": token, "reason": "spam", "details": "Repeated advert"},
        follow_redirects=False,
    )
    assert reported.status_code == 303
    report = db_session.scalar(select(ContentReport))
    assert report is not None
    assert report.status == ReportStatus.OPEN

    client.cookies.clear()
    register_and_sign_in(client, phone=STAFF_PHONE, password=PASSWORD)
    staff = user_by_phone(db_session, STAFF_PHONE)
    staff.is_staff = True
    db_session.commit()
    queue = client.get("/moderation")
    assert "Repeated advert" in queue.text
    token = csrf_from(queue)
    moderated = client.post(
        f"/moderation/reports/{report.id}",
        data={
            "csrf_token": token,
            "action": "remove",
            "note": "Commercial spam is outside this discussion.",
        },
        follow_redirects=False,
    )
    assert moderated.status_code == 303
    db_session.refresh(post)
    db_session.refresh(report)
    assert post.status == ContentStatus.REMOVED
    assert report.status == ReportStatus.RESOLVED
    assert client.get(f"/posts/{post.id}").status_code == 404
    assert "Content under review" not in client.get("/feed").text


def test_only_staff_can_create_topics_from_the_moderation_page(client, db_session):
    register_and_sign_in(client, phone=STAFF_PHONE, password=PASSWORD)
    assert client.get("/moderation").status_code == 403
    staff = user_by_phone(db_session, STAFF_PHONE)
    staff.is_staff = True
    db_session.commit()

    page = client.get("/moderation")
    token = csrf_from(page)
    response = client.post(
        "/moderation/topics",
        data={
            "csrf_token": token,
            "name": "New graduate support",
            "description": "Questions and support for new graduates.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    topic = db_session.scalar(select(CommunityTopic))
    assert topic is not None
    assert topic.slug == "new-graduate-support"


def test_only_explicitly_published_profiles_appear_in_nurse_discovery(
    client, db_session
):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    save_profile(client)
    assert "Ada Obi" not in client.get("/nurses").text

    save_sharing(client, display_name="public", headline="public")
    assert activate(client).status_code == 303

    directory = client.get("/nurses")
    assert "Ada Obi" in directory.text
    assert "New graduate seeking a first role" in directory.text
    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None and profile.discoverable is True


def test_follow_is_immediate_and_connection_requires_acceptance(client, db_session):
    register_and_sign_in(client, phone=AUTHOR_PHONE, password=PASSWORD)
    save_profile(client)
    save_sharing(client, display_name="public")
    activate(client)
    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None

    client.cookies.clear()
    register_and_sign_in(client, phone=READER_PHONE, password=PASSWORD)
    set_name(client, "Bola Reader")
    page = client.get(f"/p/{profile.public_id}")
    token = csrf_from(page)
    followed = client.post(
        f"/nurses/{profile.public_id}/follow",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert followed.status_code == 303
    assert db_session.scalar(select(Follow)) is not None

    page = client.get(f"/p/{profile.public_id}")
    token = csrf_from(page)
    requested = client.post(
        f"/nurses/{profile.public_id}/connect",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert requested.status_code == 303
    connection = db_session.scalar(select(Connection))
    assert connection is not None
    assert connection.status == ConnectionStatus.PENDING

    sign_in(client, AUTHOR_PHONE)
    network = client.get("/network")
    assert "Bola Reader" in network.text
    token = csrf_from(network)
    accepted = client.post(
        f"/connections/{connection.id}/respond",
        data={"csrf_token": token, "action": "accept"},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    db_session.refresh(connection)
    assert connection.status == ConnectionStatus.ACCEPTED


def test_malformed_public_ids_and_media_ids_are_not_found(client):
    assert client.get("/posts/not-a-uuid").status_code == 404
    assert client.get("/community/media/not-a-uuid").status_code == 404
    assert client.get(f"/posts/{uuid.uuid4()}").status_code == 404
