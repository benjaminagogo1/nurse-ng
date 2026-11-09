# ruff: noqa: F811
"""Notification permissions, atomic activity hooks and durable delivery contracts."""

import uuid
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.community import Connection, DiscussionFollow
from app.models.messages import DirectMessage
from app.models.notifications import Notification
from app.services import notifications as notices
from app.services.account_mail import MailUnavailable
from app.services.community import add_reply, connection_pair_key, respond_to_connection
from app.services.jobs import JobError, apply_for_job, change_application_status
from app.services.messages import conversation_page, mark_read, send_message, updates
from app.services.notification_worker import MAX_ATTEMPTS, run_next
from tests.helpers import csrf_from
from tests.test_discussions import as_member, community  # noqa: F401
from tests.test_workspace_flows import accounts, job  # noqa: F401


@pytest.fixture
def connected(db_session, community):
    users, _, _ = community
    first, second = users[:2]
    connection = Connection(
        requester_user_id=first.id,
        recipient_user_id=second.id,
        pair_key=connection_pair_key(first.id, second.id),
        status="accepted",
    )
    db_session.add(connection)
    db_session.commit()
    return first, second, connection


def choices(db, user, *, category="messages", in_app=True, email=False):
    values = notices.preferences(db, user)
    values[category] = {"in_app": in_app, "email": email}
    notices.save_preferences(db, user, values)


def test_reply_deduplicates_author_parent_and_follower_and_rechecks_visibility(
    db_session, community
):
    users, _, post = community
    db_session.add(
        DiscussionFollow(user_id=users[0].id, post_id=post.id, last_read_at=datetime.now(UTC))
    )
    db_session.add(
        DiscussionFollow(user_id=users[2].id, post_id=post.id, last_read_at=datetime.now(UTC))
    )
    db_session.commit()
    reply = add_reply(db_session, users[1], post, body="A useful reply")
    rows = list(db_session.scalars(select(Notification)))
    assert {row.recipient_id for row in rows} == {users[0].id, users[2].id}
    assert len(rows) == 2 and all(row.email_state == "skipped" for row in rows)
    assert notices.unread_count(db_session, users[1]) == 0
    assert notices.unread_count(db_session, users[2]) == 1
    follow = db_session.scalar(
        select(DiscussionFollow).where(DiscussionFollow.user_id == users[2].id)
    )
    db_session.delete(follow)
    db_session.commit()
    assert notices.unread_count(db_session, users[2]) == 0
    assert notices.unread_count(db_session, users[0]) == 1
    reply.status = "removed"
    db_session.commit()
    assert notices.unread_count(db_session, users[0]) == 0


def test_events_rollback_with_source_transaction(db_session, connected, monkeypatch):
    first, second, _ = connected

    def fail():
        raise RuntimeError("simulated transaction failure")

    with monkeypatch.context() as patch:
        patch.setattr(db_session, "commit", fail)
        with pytest.raises(RuntimeError):
            send_message(db_session, first, second, "Uncommitted")
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(Notification)) == 0
    assert db_session.scalar(select(func.count()).select_from(DirectMessage)) == 0


def test_connection_request_acceptance_and_removal(db_session, connected):
    first, second, connection = connected
    connection.status = "pending"
    notices.notify_connection(db_session, connection)
    db_session.commit()
    assert notices.unread_count(db_session, second) == 1
    respond_to_connection(db_session, second, connection, accept=True)
    assert notices.unread_count(db_session, second) == 0
    assert notices.unread_count(db_session, first) == 1
    db_session.delete(connection)
    db_session.commit()
    assert notices.unread_count(db_session, first) == 0


def test_application_events_noop_authorization_and_withdrawal(client, db_session, accounts, job):
    nurse, employer = accounts["nurse"], accounts["employer"]
    application = apply_for_job(db_session, nurse, job, cover_note="A private note")
    assert notices.unread_count(db_session, employer) == 1
    change_application_status(db_session, employer, application, "shortlisted")
    change_application_status(db_session, employer, application, "shortlisted")
    assert notices.unread_count(db_session, nurse) == 1
    as_member(client, accounts["other_employer"])
    assert client.get(f"/applications/{application.id}").status_code == 404
    as_member(client, nurse)
    assert client.get(f"/applications/{application.id}").status_code == 200
    change_application_status(db_session, nurse, application, "withdrawn")
    with pytest.raises(JobError):
        change_application_status(db_session, employer, application, "reviewing")
    assert application.status == "withdrawn"
    assert notices.unread_count(db_session, employer) == 2


def test_stale_application_update_cannot_override_withdrawal(db_session, accounts, job):
    application = apply_for_job(db_session, accounts["nurse"], job, cover_note="")
    with Session(db_session.bind, expire_on_commit=False) as other:
        stale = other.get(type(application), application.id)
        employer = other.get(type(accounts["employer"]), accounts["employer"].id)
        change_application_status(db_session, accounts["nurse"], application, "withdrawn")
        with pytest.raises(JobError, match="has changed"):
            change_application_status(other, employer, stale, "shortlisted")
    db_session.refresh(application)
    assert application.status == "withdrawn"


def test_preferences_default_off_and_can_disable_all(client, db_session, connected):
    first, second, _ = connected
    assert all(
        not value["email"] and value["in_app"]
        for value in notices.preferences(db_session, second).values()
    )
    choices(db_session, second, in_app=False)
    send_message(db_session, first, second, "No notification")
    assert db_session.scalar(select(Notification)) is None
    as_member(client, second)
    page = client.get("/notifications/preferences")
    assert page.status_code == 200 and "Notification preferences" in page.text
    assert client.post("/notifications/preferences", data={}).status_code == 400
    result = client.post(
        "/notifications/preferences",
        data={
            "csrf_token": csrf_from(page),
            "messages_in_app": "on",
            "messages_email": "on",
        },
    )
    assert "Preferences saved" in result.text
    send_message(db_session, first, second, "Not verified")
    row = db_session.scalar(select(Notification))
    assert row.email_state == "skipped"


def test_inbox_privacy_pagination_read_watermark_and_source_revocation(
    client, db_session, connected
):
    first, second, connection = connected
    for number in range(25):
        send_message(db_session, first, second, f"private {number}")
    as_member(client, second)
    page = client.get("/notifications")
    assert page.status_code == 200 and "data-notification-badge" in page.text
    assert "private 24" not in page.text
    assert notices.unread_count(db_session, second) == 25  # Opening inbox is not marking read.
    rows, older = notices.inbox_page(db_session, second)
    rest, end = notices.inbox_page(db_session, second, before=uuid.UUID(older))
    assert len(rows) == 20 and len(rest) == 5 and end is None
    assert not {row.id for row in rows} & {row.id for row in rest}
    watermark = rows[0].id
    send_message(db_session, first, second, "Arrived after page render")
    token = csrf_from(page)
    assert (
        client.post(
            "/notifications/read-all",
            data={"csrf_token": token, "watermark": str(watermark)},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert notices.unread_count(db_session, second) == 1
    newest = notices.inbox_page(db_session, second)[0][0]
    as_member(client, first)
    token = csrf_from(client.get("/notifications"))
    assert (
        client.post(f"/notifications/{newest.id}/open", data={"csrf_token": token}).status_code
        == 404
    )
    connection.status = "declined"
    db_session.commit()
    as_member(client, second)
    assert client.get("/notifications/summary").json()["unread"] == 0
    assert client.get(f"/messages/{first.id}/updates").status_code == 404


def test_idempotent_messages_and_complete_equal_timestamp_history(db_session, connected):
    first, second, _ = connected
    key = str(uuid.uuid4())
    original = send_message(db_session, first, second, "Once", client_key=key)
    assert send_message(db_session, first, second, "Once", client_key=key).id == original.id
    with pytest.raises(ValueError, match="already used"):
        send_message(db_session, first, second, "Different", client_key=key)
    assert notices.unread_count(db_session, second) == 1
    timestamp = datetime.now(UTC) - timedelta(days=1)
    db_session.add_all(
        [
            DirectMessage(
                sender_id=first.id,
                recipient_id=second.id,
                body=f"History {i}",
                created_at=timestamp,
            )
            for i in range(125)
        ]
    )
    db_session.commit()
    ids, before = [], None
    while True:
        rows, before = conversation_page(
            db_session, second, first, before=uuid.UUID(before) if before else None
        )
        ids.extend(row.id for row in rows)
        if not before:
            break
    assert len(ids) == len(set(ids)) == 126
    with pytest.raises(ValueError):
        conversation_page(db_session, second, first, before=uuid.uuid4())


def test_live_poll_recovers_late_commit_and_only_acknowledges_delivered_ids(
    client, db_session, connected
):
    first, second, _ = connected
    start = send_message(db_session, first, second, "Starting point")
    mark_read(db_session, second, first, [start.id])
    old = DirectMessage(
        sender_id=first.id,
        recipient_id=second.id,
        body="Late commit",
        created_at=start.created_at - timedelta(minutes=1),
    )
    db_session.add(old)
    db_session.commit()
    rows, cursor, _ = updates(db_session, second, first, after=start.id)
    assert old.id in {row.id for row in rows} and cursor == str(start.id)
    latest = send_message(db_session, first, second, "Still unread")
    as_member(client, second)
    token = csrf_from(client.get("/notifications"))
    response = client.post(
        f"/messages/{first.id}/read", data={"csrf_token": token, "ids": str(old.id)}
    )
    assert response.status_code == 200
    db_session.refresh(old)
    db_session.refresh(latest)
    assert old.read_at and latest.read_at is None
    response = client.get(f"/messages/{first.id}/updates?after={start.id}")
    assert latest.id.hex == uuid.UUID(response.json()["messages"][0]["id"]).hex
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.post(
            f"/messages/{first.id}/read", data={"csrf_token": token, "ids": "bad"}
        ).status_code
        == 400
    )


@pytest.fixture
def queued_email(db_session, connected, monkeypatch, tmp_path):
    first, second, connection = connected
    second.email_verified_at = datetime.now(UTC)
    db_session.commit()
    choices(db_session, second, email=True)
    monkeypatch.setattr(settings, "account_mail_backend", "file")
    monkeypatch.setattr(settings, "account_mail_dir", str(tmp_path / "mail"))
    monkeypatch.setattr(settings, "smtp_from", "Nurse.ng <no-reply@example.org>")
    send_message(db_session, first, second, "Do not email this private content")
    notice = db_session.scalar(select(Notification))
    return first, second, connection, notice, tmp_path / "mail"


def test_email_delivery_uses_file_mailbox_and_clears_address(db_session, queued_email):
    _, _, _, notice, directory = queued_email
    assert run_next(db_session)[1] == "sent"
    assert run_next(db_session) is None
    db_session.refresh(notice)
    assert notice.email_attempts == 1 and notice.email_to == ""
    files = list(directory.glob("*.eml"))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    mail = BytesParser(policy=policy.default).parsebytes(files[0].read_bytes())
    content = mail.get_content()
    assert "Do not email this" not in content
    assert "/notifications/preferences" in content
    assert f"notification-{notice.id.hex}" in mail["Message-ID"]


@pytest.mark.parametrize(
    "revoked", ["preference", "address", "verified", "connection", "actor", "recipient", "read"]
)
def test_email_rechecks_live_permission_before_delivery(db_session, queued_email, revoked):
    first, second, connection, notice, directory = queued_email
    if revoked == "preference":
        choices(db_session, second, email=False)
    elif revoked == "address":
        second.email = "changed@example.org"
    elif revoked == "verified":
        second.email_verified_at = None
    elif revoked == "connection":
        connection.status = "declined"
    elif revoked == "actor":
        first.is_active = False
    elif revoked == "recipient":
        second.is_active = False
    else:
        notice.read_at = datetime.now(UTC)
    db_session.commit()
    result = run_next(db_session)
    assert result is None or result[1] == "skipped"
    assert not list(directory.glob("*.eml"))


def test_email_retry_is_bounded_and_abandoned_lease_recovers(db_session, queued_email, monkeypatch):
    _, _, _, notice, _ = queued_email
    from app.services import notification_worker

    def unavailable(mail):
        raise MailUnavailable("Unavailable")

    monkeypatch.setattr(notification_worker, "deliver_mail", unavailable)
    now = datetime.now(UTC) + timedelta(seconds=1)
    notice.email_state = "sending"
    notice.email_lease_until = now + timedelta(minutes=1)
    notice.email_lease_token = "abandoned"
    db_session.commit()
    assert run_next(db_session, now=now) is None
    for attempt in range(MAX_ATTEMPTS):
        now += timedelta(days=1)
        assert run_next(db_session, now=now)[1] == (
            "failed" if attempt == MAX_ATTEMPTS - 1 else "queued"
        )
    assert run_next(db_session, now=now + timedelta(days=1)) is None
    db_session.refresh(notice)
    assert notice.email_attempts == MAX_ATTEMPTS and notice.email_lease_token is None


def test_email_only_choice_creates_no_in_app_badge(db_session, queued_email):
    first, second, _, _, _ = queued_email
    choices(db_session, second, in_app=False, email=True)
    count = notices.unread_count(db_session, second)
    send_message(db_session, first, second, "Email only")
    assert notices.unread_count(db_session, second) == count
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.email_state == "queued")
        )
        == 2
    )


def test_reply_to_nonfollower_parent_is_notified(db_session, community):
    users, _, post = community
    parent = add_reply(db_session, users[1], post, body="First response")
    add_reply(db_session, users[2], post, body="Answering you", in_reply_to_id=parent.id)
    assert notices.unread_count(db_session, users[1]) == 1
    parent.status = "removed"
    db_session.commit()
    assert notices.unread_count(db_session, users[1]) == 0


def test_poll_drains_incoming_burst_without_duplicates(db_session, connected):
    first, second, _ = connected
    start = send_message(db_session, first, second, "Start")
    mark_read(db_session, second, first, [start.id])
    expected = {send_message(db_session, first, second, f"Burst {i}").id for i in range(105)}
    delivered, cursor = set(), start.id
    for _ in range(4):
        rows, cursor, _ = updates(db_session, second, first, after=cursor)
        cursor = uuid.UUID(cursor)
        delivered.update(row.id for row in rows)
        mark_read(db_session, second, first, [row.id for row in rows])
    assert delivered == expected
    assert notices.unread_count(db_session, second) == 0


def test_active_email_lease_cannot_be_claimed_by_another_worker(
    db_session, queued_email, monkeypatch
):
    from app.services import notification_worker

    deliveries = []

    def deliver(mail):
        with Session(db_session.bind) as other:
            assert run_next(other) is None
        deliveries.append(mail)

    monkeypatch.setattr(notification_worker, "deliver_mail", deliver)
    assert run_next(db_session)[1] == "sent"
    assert len(deliveries) == 1


def test_disabling_claimed_email_clears_lease_and_prevents_delivery(db_session, queued_email):
    _, recipient, _, notice, directory = queued_email
    notice.email_state = "sending"
    notice.email_lease_token = "old-claim"
    notice.email_lease_until = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    choices(db_session, recipient, email=False)
    assert run_next(db_session) is None
    db_session.refresh(notice)
    assert notice.email_to == "" and notice.email_lease_token is None
    assert not list(directory.glob("*.eml"))


def test_open_notification_marks_only_owned_item_and_redirects(client, db_session, connected):
    first, second, _ = connected
    send_message(db_session, first, second, "One")
    send_message(db_session, first, second, "Two")
    as_member(client, second)
    token = csrf_from(client.get("/notifications"))
    notice = notices.inbox_page(db_session, second)[0][0]
    assert client.post(f"/notifications/{notice.id}/open", data={}).status_code == 400
    result = client.post(
        f"/notifications/{notice.id}/open", data={"csrf_token": token}, follow_redirects=False
    )
    assert result.status_code == 303 and result.headers["location"] == f"/messages/{first.id}"
    assert notices.unread_count(db_session, second) == 1


def test_notification_migration_preserves_messages_and_guards_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import MetaData, Table, create_engine, text

    from tests.test_migrations import historical_user

    url = f"sqlite:///{tmp_path / 'notice-migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "8cf309b2a176")
    engine = create_engine(url)
    identifier = uuid.uuid4().hex
    with Session(engine) as db:
        first = historical_user(db, phone="+2348000000091", hashed_password="unused")
        second = historical_user(db, phone="+2348000000092", hashed_password="unused")
        table = Table("direct_messages", MetaData(), autoload_with=db.connection())
        db.execute(
            table.insert().values(
                id=identifier,
                sender_id=first.id.hex,
                recipient_id=second.id.hex,
                body="Keep this conversation",
            )
        )
        db.commit()
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT body, client_key FROM direct_messages WHERE id=:id"), {"id": identifier}
        ).one()
        assert row == ("Keep this conversation", None)
        connection.execute(
            text(
                "INSERT INTO notification_preferences (user_id,category,in_app,email) "
                "VALUES (:id,'messages',1,0)"
            ),
            {"id": first.id.hex},
        )
    with pytest.raises(RuntimeError, match="Notification data exists"):
        command.downgrade(config, "8cf309b2a176")
    with engine.connect() as connection:
        assert not connection.execute(text("PRAGMA foreign_key_check")).all()
    engine.dispose()
