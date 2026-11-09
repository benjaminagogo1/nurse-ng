"""Queued contributions retain existing trust, consent and moderation rules."""

from uuid import uuid4

from sqlalchemy import func, select

from app.models.community import CommunityPost, CommunityReply, Connection
from app.models.jobs import JobApplication
from app.models.messages import DirectMessage
from app.models.offline import OfflineOperation
from app.models.profile import FieldVisibility
from app.services.community import connection_pair_key
from app.services.offline_content import contact
from app.web.community_routes import _post_limiter
from tests.test_community import create_topic, sign_in
from tests.test_offline import job, member, operation, profile


def test_queued_message_deduplicates_and_rechecks_connection(client, db_session):
    sender, recipient = member(db_session), member(db_session, "3")
    connection = Connection(
        requester_user_id=sender.id,
        recipient_user_id=recipient.id,
        pair_key=connection_pair_key(sender.id, recipient.id),
        status="accepted",
    )
    db_session.add(connection)
    db_session.commit()
    sign_in(client, sender.phone)
    payload = {
        "recipient_id": str(recipient.id),
        "body": "An offline message",
        "client_key": str(uuid4()),
    }
    identifier = uuid4()
    first = operation(client, "message", payload, identifier)
    assert first.status_code == 200, first.text
    assert operation(client, "message", payload, identifier).json() == first.json()
    assert db_session.scalar(select(func.count()).select_from(DirectMessage)) == 1
    db_session.delete(connection)
    db_session.commit()
    assert operation(client, "message", {**payload, "client_key": str(uuid4())}).status_code == 403
    assert db_session.scalar(select(func.count()).select_from(DirectMessage)) == 1


def test_queued_application_requires_current_consent_contact_and_role(client, db_session):
    user = member(db_session)
    listing = job(db_session)
    sign_in(client, user.phone)
    payload = {
        "job_id": str(listing.id),
        "cover_note": "Prepared offline",
        "consent": False,
        "contact": contact(user),
    }
    assert operation(client, "application", payload).status_code == 400
    payload["consent"] = True
    user.full_name = "Updated name"
    db_session.commit()
    assert operation(client, "application", payload).status_code == 409
    payload["contact"] = contact(user)
    user.account_type = "employer"
    db_session.commit()
    assert operation(client, "application", payload).status_code == 400
    user.account_type = "nurse"
    db_session.commit()
    identifier = uuid4()
    response = operation(client, "application", payload, identifier)
    assert response.status_code == 200, response.text
    assert operation(client, "application", payload, identifier).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(JobApplication)) == 1


def test_queued_posts_and_replies_reuse_rate_limits_and_moderation(client, db_session):
    user = member(db_session)
    topic = create_topic(db_session)
    sign_in(client, user.phone)
    payload = {
        "topic_id": str(topic.id),
        "body": "Prepared conversation",
        "community_name": "Offline Contributor",
        "external_video_url": "",
    }
    identifier = uuid4()
    response = operation(client, "post", payload, identifier)
    assert response.status_code == 200, response.text
    for _ in range(_post_limiter.limit):
        _post_limiter.record(str(user.id))
    assert operation(client, "post", payload, identifier).status_code == 200
    limited = operation(client, "post", {**payload, "body": "Another post"})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    post = db_session.scalar(select(CommunityPost))
    assert db_session.scalar(select(func.count()).select_from(CommunityPost)) == 1
    reply = {
        "post_id": str(post.id),
        "body": "Prepared reply",
        "community_name": "",
        "in_reply_to_id": "",
    }
    reply_id = uuid4()
    assert operation(client, "reply", reply, reply_id).status_code == 200
    assert operation(client, "reply", reply, reply_id).status_code == 200
    post.status = "removed"
    db_session.commit()
    assert operation(client, "reply", reply).status_code == 404
    assert db_session.scalar(select(func.count()).select_from(CommunityReply)) == 1
    assert db_session.scalar(select(func.count()).select_from(OfflineOperation)) == 2


def test_connection_requires_current_public_profile(client, db_session):
    user, target = member(db_session), member(db_session, "3")
    target_profile = profile(db_session, target)
    sign_in(client, user.phone)
    payload = {"profile_id": str(target_profile.public_id)}
    assert operation(client, "connection", payload).status_code == 404
    target_profile.status = "active"
    target_profile.discoverable = True
    db_session.add(
        FieldVisibility(profile_id=target_profile.id, field="display_name", visibility="public")
    )
    db_session.commit()
    identifier = uuid4()
    assert operation(client, "connection", payload, identifier).status_code == 200
    assert operation(client, "connection", payload, identifier).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Connection)) == 1
