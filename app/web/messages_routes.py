"""Inbox and conversations for accepted connections only."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.user import User, UserStatus
from app.services.community import list_connections, users_by_id
from app.services.messages import can_message, conversation, mark_read, send_message
from app.web.deps import require_user, verify_csrf
from app.web.templating import render

router = APIRouter(tags=["messages"])
_send_limiter = FixedWindowLimiter(60, 3600)


def _contacts(db: Session, user: User) -> list[User]:
    identifiers = {
        item.recipient_user_id if item.requester_user_id == user.id else item.requester_user_id
        for item in list_connections(db, user.id)
    }
    return sorted(
        (contact for contact in users_by_id(db, identifiers).values()
         if contact.is_active and contact.status == UserStatus.ACTIVE),
        key=lambda contact: contact.community_name.casefold(),
    )


def _recipient(db: Session, user: User, identifier: UUID) -> User:
    recipient = db.get(User, identifier)
    if recipient is None or not can_message(db, user, recipient):
        raise HTTPException(status_code=404, detail="This conversation is not available.")
    return recipient


def _inbox(request: Request, db: Session, user: User, recipient: User | None = None,
           *, error: str | None = None, body: str = "") -> Response:
    return render(request, "messages/index.html", {
        "title": "Messages", "user": user, "contacts": _contacts(db, user),
        "recipient": recipient, "messages": conversation(db, user, recipient) if recipient else [],
        "error": error, "body": body,
    }, status_code=400 if error else 200)


@router.get("/messages")
def inbox(request: Request, user: User = Depends(require_user),
          db: Session = Depends(get_db)) -> Response:
    return _inbox(request, db, user)


@router.get("/messages/{recipient_id}")
def thread(recipient_id: UUID, request: Request, user: User = Depends(require_user),
           db: Session = Depends(get_db)) -> Response:
    recipient = _recipient(db, user, recipient_id)
    mark_read(db, user, recipient)
    return _inbox(request, db, user, recipient)


@router.post("/messages/{recipient_id}")
def send(recipient_id: UUID, request: Request, body: str = Form(""),
         user: User = Depends(require_user), _: None = Depends(verify_csrf),
         db: Session = Depends(get_db)) -> Response:
    recipient = _recipient(db, user, recipient_id)
    key = str(user.id)
    if _send_limiter.is_limited(key):
        raise HTTPException(status_code=429, detail="Too many messages. Please try again later.")
    try:
        send_message(db, user, recipient, body)
    except ValueError as exc:
        return _inbox(request, db, user, recipient, error=str(exc), body=body)
    _send_limiter.record(key)
    return RedirectResponse(f"/messages/{recipient.id}#latest", status_code=303)
