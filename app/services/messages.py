"""Private, paginated conversations with idempotent sending and bounded read receipts."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import ConnectionStatus
from app.models.messages import DirectMessage
from app.models.notifications import Notification
from app.models.user import User, UserStatus
from app.services.community import connection_between
from app.services.notifications import emit

PAGE_SIZE = 40


def can_message(db: Session, user: User, recipient: User) -> bool:
    if any(
        not person.is_active or person.status != UserStatus.ACTIVE for person in (user, recipient)
    ):
        return False
    connection = connection_between(db, user.id, recipient.id)
    return connection is not None and connection.status == ConnectionStatus.ACCEPTED


def _existing(db, user, recipient, body, client_key, attachment_ids=()):
    old = db.scalar(
        select(DirectMessage).where(
            DirectMessage.sender_id == user.id,
            DirectMessage.client_key == client_key,
        )
    )
    if old and (
        old.recipient_id != recipient.id
        or old.body != body
        or [item.id for item in old.attachments] != list(attachment_ids)
    ):
        raise ValueError(
            "This send reference was already used. Reload before sending a new message."
        )
    return old


def send_message(
    db: Session,
    user: User,
    recipient: User,
    body: str,
    client_key: str | None = None,
    *,
    attachment_ids=None,
    auth_version=None,
) -> DirectMessage:
    if not can_message(db, user, recipient):
        raise ValueError("Connect with this nurse before sending a message.")
    body = body.strip()
    attachment_ids = list(attachment_ids or [])
    if (not body and not attachment_ids) or len(body) > 3000:
        raise ValueError("Write a message of up to 3,000 characters or attach a file.")
    if attachment_ids:
        from app.services.message_attachments import lock_participants

        lock_participants(db, user, recipient, auth_version=auth_version)
    if client_key:
        try:
            client_key = str(uuid.UUID(client_key))
        except ValueError:
            raise ValueError("Invalid send reference. Reload and try again.") from None
        old = _existing(db, user, recipient, body, client_key, attachment_ids)
        if old:
            return old
    message = DirectMessage(
        sender_id=user.id, recipient_id=recipient.id, body=body, client_key=client_key or None
    )
    if attachment_ids:
        from app.services.message_attachments import resolve_attachments

        for position, item in enumerate(resolve_attachments(db, user, recipient, attachment_ids)):
            item.position = position
            message.attachments.append(item)
    db.add(message)
    try:
        db.flush()
        emit(
            db,
            actor_id=user.id,
            recipients={recipient.id},
            category="messages",
            kind="message",
            event_key=f"message:{message.id}",
            message_id=message.id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if client_key and (old := _existing(db, user, recipient, body, client_key, attachment_ids)):
            return old
        raise
    db.refresh(message)
    return message


def thread_query(user, recipient):
    return select(DirectMessage).where(
        or_(
            and_(DirectMessage.sender_id == user.id, DirectMessage.recipient_id == recipient.id),
            and_(DirectMessage.sender_id == recipient.id, DirectMessage.recipient_id == user.id),
        )
    )


def _cursor(db, query, identifier):
    row = db.scalar(query.where(DirectMessage.id == identifier))
    if row is None:
        raise ValueError("This conversation position is unavailable. Reopen the conversation.")
    return row


def conversation_page(db, user, recipient, *, before=None):
    if not can_message(db, user, recipient):
        raise ValueError("This conversation is not available.")
    query = thread_query(user, recipient)
    if before:
        cursor = _cursor(db, query, before)
        query = query.where(
            or_(
                DirectMessage.created_at < cursor.created_at,
                and_(DirectMessage.created_at == cursor.created_at, DirectMessage.id < cursor.id),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc()).limit(
                PAGE_SIZE + 1
            )
        )
    )
    return list(reversed(rows[:PAGE_SIZE])), str(rows[PAGE_SIZE - 1].id) if len(
        rows
    ) > PAGE_SIZE else None


def conversation(db: Session, user: User, recipient: User) -> list[DirectMessage]:
    return conversation_page(db, user, recipient)[0]


def updates(db, user, recipient, *, after=None):
    if not can_message(db, user, recipient):
        raise ValueError("This conversation is not available.")
    query = thread_query(user, recipient)
    if after:
        cursor = _cursor(db, query, after)
        newer = query.where(
            or_(
                DirectMessage.created_at > cursor.created_at,
                and_(DirectMessage.created_at == cursor.created_at, DirectMessage.id > cursor.id),
            )
        )
        rows = list(
            db.scalars(newer.order_by(DirectMessage.created_at, DirectMessage.id).limit(PAGE_SIZE))
        )
    else:
        rows = conversation(db, user, recipient)
    # An incoming transaction can commit behind the cursor. Unacknowledged messages
    # are replayed until the recipient confirms receipt; clients deduplicate by id.
    unseen = db.scalars(
        query.where(DirectMessage.recipient_id == user.id, DirectMessage.read_at.is_(None))
        .order_by(DirectMessage.created_at, DirectMessage.id)
        .limit(PAGE_SIZE)
    )
    merged = {row.id: row for row in rows}
    merged.update({row.id: row for row in unseen})
    return (
        sorted(merged.values(), key=lambda row: (row.created_at, row.id)),
        (str(rows[-1].id) if rows else str(after) if after else None),
        len(rows) == PAGE_SIZE,
    )


def mark_read(db: Session, user: User, sender: User, ids=None) -> None:
    if not can_message(db, user, sender):
        raise ValueError("This conversation is not available.")
    if ids is None:
        ids = [row.id for row in conversation(db, user, sender)]
    valid = list(
        db.scalars(
            select(DirectMessage.id).where(
                DirectMessage.id.in_(ids),
                DirectMessage.recipient_id == user.id,
                DirectMessage.sender_id == sender.id,
            )
        )
    )
    now = datetime.now(UTC)
    db.execute(
        update(DirectMessage)
        .where(DirectMessage.id.in_(valid), DirectMessage.read_at.is_(None))
        .values(read_at=now)
    )
    db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.message_id.in_(valid),
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.commit()


def unread_count(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count(DirectMessage.id)).where(
                DirectMessage.recipient_id == user.id, DirectMessage.read_at.is_(None)
            )
        )
        or 0
    )


def message_data(message, user):
    from app.services.message_attachments import attachment_data

    timestamp = message.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return {
        "id": str(message.id),
        "body": message.body,
        "mine": message.sender_id == user.id,
        "created_at": timestamp.isoformat(),
        "client_key": message.client_key if message.sender_id == user.id else None,
        "attachments": [attachment_data(item) for item in message.attachments],
    }
