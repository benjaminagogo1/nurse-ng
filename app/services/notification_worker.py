"""Durable email outbox with expiring claims and bounded retries.

SMTP is at-least-once: a crash after acceptance can result in a duplicate on retry.
The stable Message-ID helps mail clients identify retries, but cannot guarantee deduplication.
"""

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import and_, or_, select, update

from app.core.config import settings
from app.models.notifications import Notification
from app.models.user import UserStatus
from app.services.account_mail import MailUnavailable, deliver_mail
from app.services.notifications import preferences, visible_condition

MAX_ATTEMPTS = 5
LEASE_SECONDS = 120


def ready(now):
    return or_(
        and_(Notification.email_state == "queued", Notification.email_next_attempt <= now),
        and_(Notification.email_state == "sending", Notification.email_lease_until <= now),
    )


def eligible_for_delivery(db, notice, token):
    recipient = notice.recipient
    return bool(
        notice.email_lease_token == token
        and notice.email_state == "sending"
        and recipient.is_active
        and recipient.status == UserStatus.ACTIVE
        and recipient.email_verified_at
        and recipient.email
        and recipient.email == notice.email_to
        and preferences(db, recipient).get(notice.category, {}).get("email")
        and notice.read_at is None
        and db.scalar(
            select(Notification.id).where(Notification.id == notice.id, visible_condition())
        )
    )


def deliver_notification(notice, identifier):
    mail = EmailMessage()
    mail["From"] = settings.smtp_from or "Nurse.ng <no-reply@localhost>"
    mail["To"] = notice.email_to
    mail["Subject"] = "You have a new Nurse.ng notification"
    mail["Message-ID"] = f"<notification-{identifier.hex}@nurse.ng>"
    base = settings.public_base_url.rstrip("/")
    mail.set_content(
        "There is new activity in your professional network.\n\n"
        f"Sign in to view your notifications: {base}/notifications\n\n"
        "Private messages and application details are available after signing in.\n"
        f"Manage or turn off these emails: {base}/notifications/preferences\n"
    )
    try:
        deliver_mail(mail)
        state = "sent"
    except MailUnavailable:
        state = "failed" if notice.email_attempts >= MAX_ATTEMPTS else "queued"
    return state


def run_next(db, *, now=None):
    now = now or datetime.now(UTC)
    identifier = db.scalar(
        select(Notification.id)
        .where(ready(now))
        .order_by(Notification.email_next_attempt, Notification.created_at, Notification.id)
        .limit(1)
    )
    if identifier is None:
        return None
    token = uuid.uuid4().hex
    claimed = db.execute(
        update(Notification)
        .where(Notification.id == identifier, ready(now))
        .values(
            email_state="sending",
            email_lease_token=token,
            email_lease_until=now + timedelta(seconds=LEASE_SECONDS),
        ),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    if claimed.rowcount != 1:
        return None
    # Reload after claim; other requests can disable preferences or revoke access.
    db.expire_all()
    notice = db.get(Notification, identifier)
    if not notice or notice.email_lease_token != token:
        return identifier, "skipped"
    eligible = eligible_for_delivery(db, notice, token)
    if not eligible:
        state = "skipped"
    elif notice.email_attempts >= MAX_ATTEMPTS:
        state = "failed"
    else:
        # Persist the attempt before delivery so repeated process crashes remain bounded.
        db.execute(
            update(Notification)
            .where(Notification.id == identifier, Notification.email_lease_token == token)
            .values(email_attempts=Notification.email_attempts + 1)
        )
        db.commit()
        db.expire_all()
        notice = db.get(Notification, identifier)
        if notice is None:
            return identifier, "skipped"
        state = (
            deliver_notification(notice, identifier)
            if eligible_for_delivery(db, notice, token)
            else "skipped"
        )
    values = dict(
        email_state=state,
        email_lease_until=None,
        email_lease_token=None,
        email_next_attempt=now + timedelta(seconds=60 * 2**notice.email_attempts)
        if state == "queued"
        else None,
    )
    if state in {"sent", "skipped", "failed"}:
        values["email_to"] = ""
    db.execute(
        update(Notification)
        .where(
            Notification.id == identifier,
            Notification.email_lease_token == token,
            Notification.email_state == "sending",
        )
        .values(**values),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    return identifier, state
