"""Message permissions are checked on every read and write."""

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.community import ConnectionStatus
from app.models.messages import DirectMessage
from app.models.user import User, UserStatus
from app.services.community import connection_between


def can_message(db: Session, user: User, recipient: User) -> bool:
    if not recipient.is_active or recipient.status != UserStatus.ACTIVE:
        return False
    connection = connection_between(db, user.id, recipient.id)
    return connection is not None and connection.status == ConnectionStatus.ACCEPTED


def send_message(db: Session, user: User, recipient: User, body: str) -> DirectMessage:
    if not can_message(db, user, recipient):
        raise ValueError("Connect with this nurse before sending a message.")
    body = body.strip()
    if not body or len(body) > 3000:
        raise ValueError("Write a message between 1 and 3,000 characters.")
    message = DirectMessage(sender_id=user.id, recipient_id=recipient.id, body=body)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def conversation(db: Session, user: User, recipient: User) -> list[DirectMessage]:
    if not can_message(db, user, recipient):
        raise ValueError("This conversation is not available.")
    statement = (
        select(DirectMessage)
        .where(or_(
            and_(DirectMessage.sender_id == user.id, DirectMessage.recipient_id == recipient.id),
            and_(DirectMessage.sender_id == recipient.id, DirectMessage.recipient_id == user.id),
        ))
        .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
        .limit(100)
    )
    return list(reversed(list(db.scalars(statement))))


def mark_read(db: Session, user: User, sender: User) -> None:
    if not can_message(db, user, sender):
        return
    db.execute(
        update(DirectMessage).where(
            DirectMessage.recipient_id == user.id,
            DirectMessage.sender_id == sender.id,
            DirectMessage.read_at.is_(None),
        ).values(read_at=datetime.now(UTC))
    )
    db.commit()


def unread_count(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(DirectMessage.id)).where(
            DirectMessage.recipient_id == user.id, DirectMessage.read_at.is_(None)
        )
    ) or 0
