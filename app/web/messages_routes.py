"""Inbox and conversations for accepted connections only."""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.user import User, UserStatus
from app.services.community import list_connections, users_by_id
from app.services.messages import (
    can_message,
    conversation_page,
    mark_read,
    message_data,
    send_message,
    updates,
)
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
        (
            contact
            for contact in users_by_id(db, identifiers).values()
            if contact.is_active and contact.status == UserStatus.ACTIVE
        ),
        key=lambda contact: contact.community_name.casefold(),
    )


def _recipient(db: Session, user: User, identifier: UUID) -> User:
    recipient = db.get(User, identifier)
    if recipient is None or not can_message(db, user, recipient):
        raise HTTPException(status_code=404, detail="This conversation is not available.")
    return recipient


def _json(data, status_code=200):
    return JSONResponse(data, status_code=status_code, headers={"Cache-Control": "no-store"})


def _inbox(
    request: Request,
    db: Session,
    user: User,
    recipient: User | None = None,
    *,
    error: str | None = None,
    body: str = "",
    before=None,
    client_key=None,
) -> Response:
    try:
        rows, older = (
            conversation_page(db, user, recipient, before=before) if recipient else ([], None)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if recipient and not error:
        mark_read(db, user, recipient, [row.id for row in rows])
    return render(
        request,
        "messages/index.html",
        {
            "title": "Messages",
            "user": user,
            "contacts": _contacts(db, user),
            "recipient": recipient,
            "messages": rows,
            "older": older,
            "history": bool(before),
            "error": error,
            "body": body,
            "client_key": client_key or str(uuid.uuid4()),
        },
        status_code=400 if error else 200,
    )


@router.get("/messages")
def inbox(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
) -> Response:
    return _inbox(request, db, user)


@router.get("/messages/{recipient_id}")
def thread(
    recipient_id: UUID,
    request: Request,
    before: UUID | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    return _inbox(request, db, user, _recipient(db, user, recipient_id), before=before)


@router.get("/messages/{recipient_id}/updates")
def live_updates(
    recipient_id: UUID,
    after: UUID | None = None,
    before: UUID | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    recipient = _recipient(db, user, recipient_id)
    try:
        if before:
            rows, older = conversation_page(db, user, recipient, before=before)
            return _json({"messages": [message_data(row, user) for row in rows], "older": older})
        rows, cursor, more = updates(db, user, recipient, after=after)
        return _json(
            {"messages": [message_data(row, user) for row in rows], "after": cursor, "more": more}
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/messages/{recipient_id}/read")
def read_messages(
    recipient_id: UUID,
    ids: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    recipient = _recipient(db, user, recipient_id)
    try:
        raw = ids.split(",") if ids else []
        if len(raw) > 100:
            raise ValueError
        identifiers = [UUID(value) for value in raw]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid read receipt.") from None
    mark_read(db, user, recipient, identifiers)
    return _json({"ok": True})


@router.post("/messages/{recipient_id}")
def send(
    recipient_id: UUID,
    request: Request,
    body: str = Form(""),
    client_key: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    recipient = _recipient(db, user, recipient_id)
    key = str(user.id)
    enhanced = request.headers.get("x-messages") == "1"
    if _send_limiter.is_limited(key):
        return (
            _json({"error": "Too many messages. Please try again later."}, 429)
            if enhanced
            else (
                _inbox(
                    request,
                    db,
                    user,
                    recipient,
                    error="Too many messages. Please try again later.",
                    body=body,
                    client_key=client_key,
                )
            )
        )
    try:
        message = send_message(db, user, recipient, body, client_key=client_key or None)
    except ValueError as exc:
        if enhanced:
            return _json({"error": str(exc)}, 400)
        return _inbox(
            request, db, user, recipient, error=str(exc), body=body, client_key=client_key
        )
    _send_limiter.record(key)
    if enhanced:
        return _json({"message": message_data(message, user)})
    return RedirectResponse(f"/messages/{recipient.id}#latest", status_code=303)
