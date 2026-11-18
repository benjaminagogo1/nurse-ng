"""Real PostgreSQL checks for growth transactions and competing worker passes."""

import os
import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

if not os.environ.get("NURSE_NG_TEST_POSTGRES_URL", "").endswith("/nurse_ng_hosting_test"):
    raise RuntimeError("Use an isolated PostgreSQL database named nurse_ng_hosting_test.")

# The existing hosted journey establishes production config, migrations and sign-up.
runpy.run_path(str(Path(__file__).with_name("postgres_journey.py")))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.activity import UserDailyActivity  # noqa: E402
from app.models.community import CommunityPost, CommunityTopic  # noqa: E402
from app.models.participation import ActivityOccurrence, MemberReferral, Mentorship  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import community_participation as participation  # noqa: E402
from app.services import member_invitations as invitations  # noqa: E402
from app.services import mentorship, weekly_digest  # noqa: E402
from app.services.community import CommunityError, add_reply, create_post  # noqa: E402

with SessionLocal() as db:
    users = [
        User(
            phone=f"+23489993330{i:02}",
            hashed_password="unused",
            community_name=f"Postgres colleague {i}",
            community_name_key=f"postgres colleague {i}",
            email=f"postgres-peer-{i}@example.org",
            email_verified_at=datetime.now(UTC),
        )
        for i in range(3)
    ]
    db.add_all(users)
    db.flush()
    ids = [user.id for user in users]
    topic = db.scalar(select(CommunityTopic).where(CommunityTopic.name == "Hosted peer learning"))
    topic_id = topic.id
    topic_slug, topic_host_id = topic.slug, topic.created_by_user_id
    db.commit()
    mentorship.save_offer(
        db,
        users[0],
        topics=["school", "research"],
        introduction="Study and research support",
        availability="Weekends",
        capacity=1,
        accepting=True,
    )
    request_ids = [
        mentorship.request_support(db, user, ids[0], topic="school", goal="Study help").id
        for user in users[1:]
    ]


def accept_request(identifier):
    with SessionLocal() as db:
        try:
            mentorship.respond(db, db.get(User, ids[0]), identifier, "accept")
            return "accepted"
        except CommunityError:
            db.rollback()
            return "full"


with ThreadPoolExecutor(max_workers=2) as workers:
    assert sorted(workers.map(accept_request, request_ids)) == ["accepted", "full"]

with SessionLocal() as db:
    assert (
        db.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.mentor_id == ids[0], Mentorship.status == "accepted")
        )
        == 1
    )
    learner = db.get(User, ids[1])
    host = db.get(User, ids[0])
    intro = participation.introduce(
        db, learner, topic_id=topic_id, body="Hello from nursing school"
    )
    add_reply(db, db.get(User, topic_host_id), intro, "Welcome to our community")
    participation.acknowledge_welcome(db, db.get(User, topic_host_id), intro.id)
    now = datetime.now(UTC)
    starts = now + timedelta(days=2)
    series = participation.create_series(
        db,
        host,
        identifier=uuid4(),
        topic_id=topic_id,
        title="Weekly study circle",
        instructions="Discuss a practice question",
        activity_format="practice",
        starts_at=starts.strftime("%Y-%m-%dT18:00"),
        now=now,
    )
    series_id, due = series.id, series.next_starts_at - timedelta(hours=23)


def activity_pass(_):
    with SessionLocal() as db:
        return participation.run_next_activity(db, now=due)


with ThreadPoolExecutor(max_workers=2) as workers:
    outcomes = list(workers.map(activity_pass, range(2)))
    assert len([outcome for outcome in outcomes if outcome]) == 1, outcomes

with SessionLocal() as db:
    host, learner = db.get(User, ids[0]), db.get(User, ids[1])
    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivityOccurrence)
            .where(ActivityOccurrence.series_id == series_id)
        )
        == 2
    )
    latest = db.scalar(
        select(CommunityPost)
        .join(ActivityOccurrence)
        .where(ActivityOccurrence.series_id == series_id)
        .order_by(ActivityOccurrence.starts_at.desc())
    )
    participation.attendance(db, learner, latest.id, attending=True)
    assert participation.activity_details(db, latest, host)["count"] == 1
    invite = invitations.create_invitation(db, host, destination=f"/topics/{topic_slug}")
    token = invitations.invitation_link(invite).split("/invite/")[1]
    invitations.attribute_signup(db, SimpleNamespace(session={"pending_referral": token}), learner)
    db.commit()
    tomorrow = now + timedelta(days=1)
    db.add(
        UserDailyActivity(
            user_id=learner.id,
            activity_date=tomorrow.date(),
            first_seen_at=tomorrow,
            last_seen_at=tomorrow,
        )
    )
    db.commit()
    assert db.get(MemberReferral, learner.id)
    summary = invitations.summaries(db, host)[0]
    assert summary["signups"] == summary["contributors"] == summary["returning"] == 1
    create_post(db, host, topic_id=topic_id, body="What helps you learn?", post_kind="question")
    pref = weekly_digest.save_preferences(db, learner, enabled=True, questions=True)
    pref.next_due_at = now - timedelta(seconds=1)
    db.commit()
    weekly_digest.enqueue(db, now=now)

messages = []
weekly_digest.deliver_mail = messages.append  # Isolated transport; no SMTP or real recipients.


def digest_pass(_):
    with SessionLocal() as db:
        return weekly_digest.run_next(db, now=now)


with ThreadPoolExecutor(max_workers=2) as workers:
    outcomes = list(workers.map(digest_pass, range(2)))
    assert len(messages) == 1, outcomes

with SessionLocal() as db:
    pref = db.get(
        __import__("app.models.participation", fromlist=["DigestPreference"]).DigestPreference,
        ids[1],
    )
    assert weekly_digest.unsubscribe(db, ids[1], weekly_digest.unsubscribe_token(pref))

print(
    "PostgreSQL engagement passed: capacity race, recurring-session race, welcome, attendance, "
    "referral participation, digest claim race and unsubscribe."
)
