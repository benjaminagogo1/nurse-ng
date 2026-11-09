"""Deferred contributions use the same validation, permissions and rate limits as forms."""

from uuid import UUID

from sqlalchemy import select

from app.models.jobs import Job
from app.models.profile import NurseProfile
from app.models.user import User
from app.services import community, jobs, messages
from app.services.offline import SyncError
from app.services.profiles import discoverable_condition


def fields(payload, expected):
    if set(payload) != set(expected.split()):
        raise SyncError("The saved form is incomplete. Reopen it while connected.")
    for name, value in payload.items():
        expected_type = {
            "consent": bool,
            "contact": dict,
            "cover_seconds": int,
            "file_size": int,
        }.get(name, str)
        if type(value) is not expected_type:
            raise SyncError("A saved form field has an invalid value.")


def limit(user, kind):
    # Import lazily so services do not create a web-router import cycle.
    from app.web.community_routes import _post_limiter, _reply_limiter, _retry_after
    from app.web.messages_routes import _send_limiter

    limiter = {"message": _send_limiter, "post": _post_limiter, "reply": _reply_limiter}[kind]
    retry = _retry_after(limiter, user)
    if retry:
        raise SyncError(
            "Please wait before sending more contributions.", status=429, retry_after=retry
        )


def message(db, user, payload):
    fields(payload, "recipient_id body client_key")
    recipient = db.get(User, UUID(payload["recipient_id"]))
    if recipient is None or not messages.can_message(db, user, recipient):
        raise SyncError("This connection is no longer available for messaging.", status=403)
    limit(user, "message")
    sent = messages.send_message(db, user, recipient, payload["body"], payload["client_key"])
    return {
        "path": f"/messages/{recipient.id}",
        "message": "Message delivered to Nurse.ng.",
        "id": str(sent.id),
    }


def contact(user):
    return {"name": user.full_name, "phone": user.phone, "email": user.email or ""}


def application(db, user, payload):
    fields(payload, "job_id cover_note consent contact")
    if payload["consent"] is not True:
        raise SyncError("Review and agree to share your contact details before applying.")
    if payload["contact"] != contact(user):
        raise SyncError(
            "Your contact details changed. Reopen the application and review consent.", status=409
        )
    job = db.get(Job, UUID(payload["job_id"]))
    if job is None:
        raise SyncError("This opportunity is no longer available.", status=404)
    item = jobs.apply_for_job(db, user, job, cover_note=payload["cover_note"])
    return {
        "path": "/applications",
        "message": "Application submitted to the employer.",
        "id": str(item.id),
    }


def _name(db, user, value):
    if not user.community_name and value.strip():
        community.set_community_name(db, user, value)


def post(db, user, payload):
    fields(payload, "topic_id body community_name external_video_url")
    limit(user, "post")
    _name(db, user, payload["community_name"])
    item = community.create_post(
        db,
        user,
        topic_id=UUID(payload["topic_id"]),
        body=payload["body"],
        external_video_url=payload["external_video_url"],
    )
    return {"path": f"/posts/{item.id}", "message": "Conversation published.", "id": str(item.id)}


def reply(db, user, payload):
    fields(payload, "post_id body community_name in_reply_to_id")
    target = community.get_published_post(db, UUID(payload["post_id"]))
    if target is None:
        raise SyncError("This conversation is no longer available.", status=404)
    limit(user, "reply")
    _name(db, user, payload["community_name"])
    item = community.add_reply(
        db,
        user,
        target,
        payload["body"],
        in_reply_to_id=UUID(payload["in_reply_to_id"]) if payload["in_reply_to_id"] else None,
    )
    return {
        "path": f"/posts/{target.id}/replies/{item.id}",
        "message": "Reply published.",
        "id": str(item.id),
    }


def connection(db, user, payload):
    fields(payload, "profile_id")
    target = db.scalar(
        select(NurseProfile).where(
            NurseProfile.public_id == UUID(payload["profile_id"]),
            discoverable_condition(),
        )
    )
    if target is None:
        raise SyncError("This profile is no longer public.", status=404)
    item = community.request_connection(db, user, target)
    return {"path": "/network", "message": "Connection request synchronized.", "id": str(item.id)}


HANDLERS = {
    "message": message,
    "application": application,
    "post": post,
    "reply": reply,
    "connection": connection,
}
