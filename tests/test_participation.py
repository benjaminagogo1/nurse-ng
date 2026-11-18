"""End-to-end permissions, consent, retries and retention for community growth."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.main import app
from app.models.activity import UserDailyActivity
from app.models.community import (
    CommunityPost,
    CommunityTopic,
    Connection,
    ContentStatus,
    DiscussionFollow,
)
from app.models.notifications import Notification
from app.models.participation import (
    ActivityAttendance,
    ActivityOccurrence,
    DigestPreference,
    MemberReferral,
    MentorOffer,
    MentorReport,
    Mentorship,
    ReferralVisit,
    WeeklyDigest,
)
from app.models.user import User, UserStatus
from app.services import community_participation as participation
from app.services import member_invitations as invitations
from app.services import mentorship, weekly_digest
from app.services.community import CommunityError, add_reply, create_post, remove_connection
from app.services.community_growth import recognize_reply
from app.services.notifications import card, inbox_page
from app.web.deps import get_current_user
from tests.helpers import csrf_from, has_element, register_payload


@pytest.fixture
def members(db_session, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://members.nurse.example")
    rows = [
        User(
            phone=f"+23489991100{i:02}",
            hashed_password="unused",
            community_name=f"Colleague {i}",
            community_name_key=f"colleague {i}",
            full_name=f"PRIVATE NAME {i}",
            email=f"private-{i}@example.org",
            email_verified_at=datetime.now(UTC),
        )
        for i in range(4)
    ]
    db_session.add_all(rows)
    db_session.flush()
    topic = CommunityTopic(
        name="Nursing from school to professorship",
        slug="every-stage",
        description="Every stage is welcome",
        created_by_user_id=rows[0].id,
    )
    db_session.add(topic)
    db_session.commit()
    return rows, topic


def login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def offer(db, user, **changes):
    return mentorship.save_offer(
        db,
        user,
        topics=["school", "research", "teaching"],
        introduction="Peer support from nursing school to postgraduate research.",
        availability="Weekend conversations",
        capacity=2,
        accepting=True,
        **changes,
    )


def support(db, members):
    users, _ = members
    offer(db, users[0])
    return mentorship.request_support(
        db,
        users[1],
        users[0].id,
        topic="school",
        goal="PRIVATE GOAL: prepare for my first placement",
    )


def series(db, members, **changes):
    users, topic = members
    return participation.create_series(
        db,
        users[0],
        identifier=uuid4(),
        topic_id=topic.id,
        title="Weekly teaching and study circle",
        instructions="Discuss a practice question.",
        activity_format="q-and-a",
        starts_at="2027-01-04T18:00",
        now=datetime(2027, 1, 1, tzinfo=UTC),
        **changes,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/mentorship",
        "/mentorship/offer",
        "/mentorship/requests",
        "/community/start",
        "/activities/series",
        "/activities/series/new",
        "/invitations",
        "/digest",
    ],
)
def test_private_growth_pages_require_signin(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


@pytest.mark.parametrize(
    "path",
    [
        "/mentorship/offer",
        "/community/start/preferences",
        "/community/start/introduction",
        "/activities/series",
        "/invitations",
        "/digest",
    ],
)
def test_growth_changes_require_csrf(client, members, path):
    login_as(members[0][0])
    assert client.post(path, data={}).status_code == 400


def test_member_screens_render_without_exposing_private_names(client, db_session, members):
    users, _ = members
    offer(db_session, users[0])
    login_as(users[1])
    for path in [
        "/mentorship",
        "/mentorship/offer",
        "/community/start",
        "/invitations",
        "/digest",
        "/activities/series/new",
        "/activities/series",
        "/mentorship/requests",
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "PRIVATE NAME 0" not in response.text
        assert "private-0@example.org" not in response.text
    assert "Starting nursing school" in client.get("/mentorship?topic=school").text
    assert "Colleague 0" not in client.get("/mentorship?topic=career").text


def test_support_offer_pause_and_current_account_state(client, db_session, members):
    users, _ = members
    current = offer(db_session, users[0])
    login_as(users[1])
    current.accepting = False
    db_session.commit()
    assert "Colleague 0" not in client.get("/mentorship").text
    assert client.get(f"/mentorship/offers/{users[0].id}").status_code == 404
    current.accepting = True
    users[0].status = UserStatus.SUSPENDED
    db_session.commit()
    assert "Colleague 0" not in client.get("/mentorship").text
    assert client.get(f"/mentorship/offers/{users[0].id}").status_code == 404


def test_support_is_private_and_only_participants_can_change_it(client, db_session, members):
    users, _ = members
    item = support(db_session, members)
    login_as(users[2])
    assert client.get(f"/mentorship/requests/{item.id}").status_code == 404
    with pytest.raises(CommunityError):
        mentorship.respond(db_session, users[2], item.id, "accept")
    assert "PRIVATE GOAL" not in client.get("/mentorship").text
    login_as(users[0])
    response = client.get(f"/mentorship/requests/{item.id}")
    assert "PRIVATE GOAL" in response.text
    assert "PRIVATE NAME 1" not in response.text
    rows, _ = inbox_page(db_session, users[0])
    notice = next(row for row in rows if row.category == "mentorship")
    assert card(db_session, notice)["path"] == f"/mentorship/requests/{item.id}"


def test_acceptance_capacity_completion_and_messaging(db_session, members):
    users, _ = members
    item = support(db_session, members)
    assert db_session.scalar(select(func.count()).select_from(Connection)) == 0
    again = mentorship.request_support(
        db_session, users[1], users[0].id, topic="school", goal="Retry"
    )
    assert again.id == item.id
    accepted = mentorship.respond(db_session, users[0], item.id, "accept")
    connection = db_session.get(Connection, accepted.connection_id)
    assert connection.status == "accepted"
    with pytest.raises(CommunityError):
        mentorship.respond(db_session, users[0], item.id, "accept")
    other = mentorship.request_support(
        db_session, users[2], users[0].id, topic="research", goal="Research guidance"
    )
    mentorship.respond(db_session, users[0], other.id, "accept")
    third = mentorship.request_support(
        db_session, users[3], users[0].id, topic="teaching", goal="Teach well"
    )
    with pytest.raises(CommunityError, match="capacity"):
        mentorship.respond(db_session, users[0], third.id, "accept")
    mentorship.respond(db_session, users[1], item.id, "complete")
    mentorship.respond(db_session, users[0], third.id, "accept")
    assert item.open_pair is None
    remove_connection(db_session, users[1], connection)
    assert db_session.get(Connection, accepted.connection_id) is None


@pytest.mark.parametrize(
    "actor,action", [(0, "withdraw"), (1, "decline"), (1, "accept"), (0, "complete"), (1, "end")]
)
def test_invalid_support_transitions_are_rejected(db_session, members, actor, action):
    item = support(db_session, members)
    with pytest.raises(CommunityError):
        mentorship.respond(db_session, members[0][actor], item.id, action)


def test_support_report_is_deduplicated_and_staff_only(client, db_session, members):
    users, _ = members
    item = support(db_session, members)
    report = mentorship.report(db_session, users[1], item.id, reason="privacy", details="Concern")
    assert (
        mentorship.report(db_session, users[1], item.id, reason="privacy", details="Retry").id
        == report.id
    )
    login_as(users[1])
    assert client.get("/staff/mentorship-reports").status_code == 403
    users[3].is_staff = True
    db_session.commit()
    login_as(users[3])
    assert "Concern" in client.get("/staff/mentorship-reports").text
    mentorship.review_report(db_session, users[3], report.id, "resolve")
    assert db_session.get(MentorReport, report.id).status == "resolved"


def test_intro_is_idempotent_public_and_host_welcome_requires_real_reply(
    client, db_session, members
):
    users, topic = members
    post = participation.introduce(
        db_session,
        users[1],
        topic_id=topic.id,
        body="Hello, I am on my first day in nursing school.",
    )
    assert (
        participation.introduce(db_session, users[1], topic_id=topic.id, body="Retry").id == post.id
    )
    assert participation.progress(db_session, users[1])["joined"] == 1
    assert participation.welcome_queue(db_session, users[0], topic)[0].id == post.id
    with pytest.raises(CommunityError):
        participation.welcome_queue(db_session, users[2], topic)
    with pytest.raises(CommunityError, match="Reply"):
        participation.acknowledge_welcome(db_session, users[0], post.id)
    add_reply(db_session, users[0], post, "Welcome. We are glad you are here.")
    participation.acknowledge_welcome(db_session, users[0], post.id)
    assert participation.welcome_queue(db_session, users[0], topic) == []
    login_as(users[0])
    assert client.get(f"/communities/{topic.slug}/welcomes").status_code == 200


def test_introduction_requires_public_consent_and_preserves_errors(client, db_session, members):
    users, topic = members
    login_as(users[1])
    token = csrf_from(client.get("/community/start"))
    response = client.post(
        "/community/start/introduction",
        data={"csrf_token": token, "topic_id": str(topic.id), "body": "Keep my introduction"},
    )
    assert response.status_code == 400
    assert "Keep my introduction" in response.text
    assert db_session.scalar(select(func.count()).select_from(CommunityPost)) == 0


def test_recognition_is_optin_and_removed_replies_stop_counting(db_session, members):
    users, topic = members
    post = create_post(db_session, users[0], topic_id=topic.id, body="A question")
    reply = add_reply(db_session, users[1], post, "A helpful response")
    recognize_reply(db_session, users[2], reply.id, marked=True)
    assert participation.recognition_summaries(db_session, {users[1].id}) == {}
    participation.save_journey(db_session, users[1], goal="school", show_recognition=True)
    assert participation.recognition_summaries(db_session, {users[1].id}) == {users[1].id: 1}
    reply.status = ContentStatus.REMOVED
    db_session.commit()
    assert participation.recognition_summaries(db_session, {users[1].id}) == {}


def test_series_publishing_schedule_and_duplicate_worker_passes(db_session, members):
    item = series(db_session, members)
    starts = datetime(2027, 1, 11, 17, tzinfo=UTC)
    assert participation.run_next_activity(db_session, now=starts - timedelta(days=2)) is None
    assert (
        participation.run_next_activity(db_session, now=starts - timedelta(hours=23))[1]
        == "published"
    )
    assert participation.run_next_activity(db_session, now=starts - timedelta(hours=23)) is None
    assert db_session.scalar(select(func.count()).select_from(ActivityOccurrence)) == 2
    participation.set_series_active(db_session, members[0][0], item.id, False)
    assert participation.run_next_activity(db_session, now=starts + timedelta(days=7)) is None
    with pytest.raises(CommunityError):
        participation.set_series_active(db_session, members[0][2], item.id, True)


def test_series_submission_reference_prevents_duplicate_first_sessions(db_session, members):
    users, topic = members
    identifier = uuid4()
    values = dict(
        identifier=identifier,
        topic_id=topic.id,
        title="Research circle",
        instructions="Discuss research methods",
        activity_format="discussion",
        starts_at="2027-01-04T18:00",
        now=datetime(2027, 1, 1, tzinfo=UTC),
    )
    first = participation.create_series(db_session, users[0], **values)
    assert participation.create_series(db_session, users[0], **values).id == first.id
    assert db_session.scalar(select(func.count()).select_from(ActivityOccurrence)) == 1


def test_local_session_time_and_digest_delivery_preserve_daylight_saving():
    spring = datetime(2027, 3, 22, 18, tzinfo=UTC)
    assert participation.next_start(spring, 7, "Europe/London") == datetime(
        2027, 3, 29, 17, tzinfo=UTC
    )
    assert weekly_digest.next_due(
        datetime(2027, 3, 27, 12, tzinfo=UTC), 0, "Europe/London"
    ) == datetime(2027, 3, 29, 8, tzinfo=UTC)


def test_old_series_does_not_backfill_missed_sessions(db_session, members):
    series(db_session, members)
    assert (
        participation.run_next_activity(db_session, now=datetime(2027, 5, 1, tzinfo=UTC))[1]
        == "missed"
    )
    assert db_session.scalar(select(func.count()).select_from(ActivityOccurrence)) == 1


def test_activity_attendance_is_private_idempotent_and_follows_replies(client, db_session, members):
    users, _ = members
    series(db_session, members)
    post = db_session.scalar(select(CommunityPost))
    participation.attendance(db_session, users[1], post.id, attending=True)
    participation.attendance(db_session, users[1], post.id, attending=True)
    assert db_session.get(ActivityAttendance, (post.id, users[1].id))
    assert db_session.scalar(
        select(DiscussionFollow).where(DiscussionFollow.user_id == users[1].id)
    )
    details = participation.activity_details(db_session, post, users[0])
    assert details["count"] == 1 and not details["attending"]
    login_as(users[0])
    response = client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert "PRIVATE NAME 1" not in response.text
    assert has_element(response, "form", action=f"/activities/{post.id}/attendance")
    participation.attendance(db_session, users[1], post.id, attending=False)
    assert participation.activity_details(db_session, post, users[0])["count"] == 0


def test_personal_invitation_continues_signup_and_tracks_only_new_accounts(
    client, db_session, members
):
    users, topic = members
    item = invitations.create_invitation(db_session, users[0], destination=f"/topics/{topic.slug}")
    token = invitations.invitation_link(item).split("/invite/")[1]
    landing = client.get("/invite/" + token)
    assert landing.status_code == 200
    assert "PRIVATE NAME 0" not in landing.text
    client.get("/invite/" + token)
    assert db_session.scalar(select(func.count()).select_from(ReferralVisit)) == 1
    form = client.get(f"/auth/register?next=/topics/{topic.slug}")
    response = client.post(
        "/auth/register",
        data={
            "csrf_token": csrf_from(form),
            "next": f"/topics/{topic.slug}",
            **register_payload("+2348999110099"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/topics/{topic.slug}"
    referred = db_session.scalar(select(MemberReferral))
    assert referred.inviter_id == users[0].id
    assert invitations.summaries(db_session, users[0])[0]["signups"] == 1
    assert db_session.scalar(select(func.count()).select_from(MemberReferral)) == 1
    new_user = db_session.get(User, referred.user_id)
    new_user.community_name = "New community colleague"
    new_user.community_name_key = "new community colleague"
    db_session.commit()
    create_post(db_session, new_user, topic_id=topic.id, body="My first useful question")
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    db_session.add(
        UserDailyActivity(
            user_id=new_user.id,
            activity_date=tomorrow.date(),
            first_seen_at=tomorrow,
            last_seen_at=tomorrow,
        )
    )
    db_session.commit()
    summary = invitations.summaries(db_session, users[0])[0]
    assert summary["contributors"] == summary["returning"] == 1


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.example",
        "//evil.example",
        "/settings",
        "/topics/missing",
        "/posts/" + str(uuid4()),
    ],
)
def test_referrals_accept_only_available_public_destinations(db_session, members, destination):
    with pytest.raises(CommunityError):
        invitations.create_invitation(db_session, members[0][0], destination=destination)


def test_revoked_or_expired_invites_do_not_attribute(db_session, members):
    users, topic = members
    item = invitations.create_invitation(db_session, users[0], destination=f"/topics/{topic.slug}")
    token = invitations.invitation_link(item).split("/invite/")[1]
    assert invitations.resolve(db_session, token)
    assert invitations.resolve(db_session, token + "tamper") is None
    assert (
        invitations.resolve(db_session, token, now=datetime.now(UTC) + timedelta(days=91)) is None
    )
    with pytest.raises(CommunityError):
        invitations.revoke(db_session, users[1], item.id)
    invitations.revoke(db_session, users[0], item.id)
    invitations.attribute_signup(
        db_session, SimpleNamespace(session={"pending_referral": token}), users[1]
    )
    db_session.commit()
    assert db_session.get(MemberReferral, users[1].id) is None


def digest_fixture(db, members):
    users, topic = members
    participation.introduce(db, users[1], topic_id=topic.id, body="Hello")
    question = create_post(
        db, users[0], topic_id=topic.id, body="What helps on placement?", post_kind="question"
    )
    now = datetime.now(UTC)
    pref = weekly_digest.save_preferences(
        db, users[1], enabled=True, questions=True, weekday=now.weekday(), now=now
    )
    pref.next_due_at = now - timedelta(seconds=1)
    db.commit()
    weekly_digest.enqueue(db, now=now)
    return users[1], pref, question, now


def test_digest_is_optin_requires_verified_email_and_has_live_highlights(db_session, members):
    users, _ = members
    assert db_session.get(DigestPreference, users[1].id) is None
    users[1].email_verified_at = None
    with pytest.raises(CommunityError, match="Verify"):
        weekly_digest.save_preferences(db_session, users[1], enabled=True, questions=True)
    users[1].email_verified_at = datetime.now(UTC)
    user, pref, question, now = digest_fixture(db_session, members)
    assert any(
        row["path"] == f"/posts/{question.id}"
        for row in weekly_digest.highlights(db_session, user, pref)
    )
    add_reply(db_session, users[2], question, "A useful answer")
    assert not weekly_digest.highlights(db_session, user, pref, now=now)


def test_digest_send_is_bounded_private_and_once_per_week(db_session, members, monkeypatch):
    user, pref, question, now = digest_fixture(db_session, members)
    mails = []
    monkeypatch.setattr(weekly_digest, "deliver_mail", mails.append)
    assert weekly_digest.run_next(db_session, now=now)[1] == "sent"
    assert weekly_digest.run_next(db_session, now=now) is None
    assert len(mails) == 1
    assert mails[0]["To"] == user.email
    assert f"https://members.nurse.example/posts/{question.id}" in mails[0].get_content()
    assert "PRIVATE NAME" not in mails[0].get_content()
    pref.next_due_at = now
    db_session.commit()
    weekly_digest.enqueue(db_session, now=now)
    assert db_session.scalar(select(func.count()).select_from(WeeklyDigest)) == 1


@pytest.mark.parametrize("change", ["disable", "unverify", "suspend", "remove", "leave"])
def test_digest_rechecks_preferences_accounts_and_content(db_session, members, monkeypatch, change):
    user, pref, question, now = digest_fixture(db_session, members)
    mails = []
    monkeypatch.setattr(weekly_digest, "deliver_mail", mails.append)
    if change == "disable":
        pref.enabled = False
    elif change == "unverify":
        user.email_verified_at = None
    elif change == "suspend":
        user.status = UserStatus.SUSPENDED
    elif change == "remove":
        question.status = ContentStatus.REMOVED
    elif change == "leave":
        from app.services.community_growth import membership

        membership(db_session, user, question.topic, joined=False)
    db_session.commit()
    assert weekly_digest.run_next(db_session, now=now)[1] == "skipped"
    assert mails == []


def test_digest_retries_are_bounded_and_unsubscribe_cancels_claims(
    client, db_session, members, monkeypatch
):
    from app.services.account_mail import MailUnavailable

    user, pref, _, now = digest_fixture(db_session, members)

    def unavailable(mail):
        raise MailUnavailable("isolated failure")

    monkeypatch.setattr(weekly_digest, "deliver_mail", unavailable)
    assert weekly_digest.run_next(db_session, now=now)[1] == "queued"
    token = weekly_digest.unsubscribe_token(pref)
    path = f"/digest/unsubscribe/{user.id}/{token}"
    assert client.get(path).status_code == 200
    assert pref.enabled
    assert client.post(path).status_code == 200
    assert not pref.enabled
    assert db_session.scalar(select(WeeklyDigest)).state == "skipped"
    assert weekly_digest.run_next(db_session, now=now + timedelta(days=1)) is None
    assert client.post(f"/digest/unsubscribe/{user.id}/bad").status_code == 404


def test_growth_data_and_notices_cascade_on_account_deletion(db_session, members):
    users, _ = members
    item = support(db_session, members)
    series(db_session, members)
    assert db_session.scalar(select(Notification).where(Notification.mentorship_id == item.id))
    db_session.delete(users[0])
    db_session.commit()
    assert db_session.scalar(select(Mentorship.id).where(Mentorship.id == item.id)) is None
    assert db_session.scalar(select(func.count()).select_from(MentorOffer)) == 0
    assert db_session.scalar(select(func.count()).select_from(ActivityOccurrence)) == 0


def test_staff_can_review_reported_goal_and_pause_the_offer(client, db_session, members):
    users, _ = members
    item = support(db_session, members)
    report = mentorship.report(
        db_session, users[1], item.id, reason="harassment", details="Concern"
    )
    users[3].is_staff = True
    db_session.commit()
    login_as(users[3])
    response = client.get("/staff/mentorship-reports")
    assert "PRIVATE GOAL" in response.text
    assert users[0].full_name not in response.text
    assert users[1].full_name not in response.text
    result = client.post(
        f"/staff/mentorship-reports/{report.id}/pause",
        data={"csrf_token": csrf_from(response)},
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert not db_session.get(MentorOffer, users[0].id).accepting
    assert db_session.get(MentorReport, report.id).status == "resolved"


def test_text_only_engagement_forms_reject_uploaded_fields(client, members):
    login_as(members[0][1])
    response = client.post(
        "/community/start/preferences",
        data={"csrf_token": csrf_from(client.get("/community/start"))},
        files={"goal": ("goal.txt", b"school", "text/plain")},
    )
    assert response.status_code == 400
