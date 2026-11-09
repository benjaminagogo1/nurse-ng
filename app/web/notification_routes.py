"""Private notification feed, read actions and opt-in channel preferences."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.notifications import Notification
from app.models.user import User
from app.services import notifications as service
from app.web.deps import require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _latest(db, user):
    return db.scalar(
        service.inbox_query(user)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(1)
    )


@router.get("")
def inbox(
    request: Request,
    category: str = "",
    unread: bool = False,
    before: UUID | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    category = category if category in service.CATEGORIES else ""
    rows, next_page = service.inbox_page(db, user, category=category, unread=unread, before=before)
    latest = _latest(db, user)
    return render(
        request,
        "notifications/index.html",
        {
            "user": user,
            "title": "Notifications",
            "cards": [service.card(db, row) for row in rows],
            "categories": service.CATEGORIES,
            "category": category,
            "unread": unread,
            "next_page": next_page,
            "watermark": str(latest.id) if latest else "",
        },
    )


@router.get("/summary")
def summary(user: User = Depends(require_user), db: Session = Depends(get_db)):
    latest = _latest(db, user)
    return JSONResponse(
        {"unread": service.unread_count(db, user), "latest": str(latest.id) if latest else ""},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/preferences")
def preferences(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    return render(
        request,
        "notifications/preferences.html",
        {
            "title": "Notification preferences",
            "user": user,
            "categories": service.CATEGORIES,
            "choices": service.preferences(db, user),
        },
    )


@router.post("/preferences")
async def save_preferences(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    form = await request.form()
    values = {
        category: {
            channel: form.get(f"{category}_{channel}") == "on" for channel in ("in_app", "email")
        }
        for category in service.CATEGORIES
    }
    service.save_preferences(db, user, values)
    return redirect_feedback(
        request,
        "/notifications/preferences",
        message("Preferences saved", "Your notification choices apply to new activity."),
    )


@router.post("/read-all")
def read_all(
    request: Request,
    watermark: UUID = Form(...),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    cursor = service.get_notice(db, user, watermark)
    if cursor is None:
        raise HTTPException(status_code=404, detail="Refresh your notifications and try again.")
    ids = service.inbox_query(user).where(
        or_(
            Notification.created_at < cursor.created_at,
            and_(Notification.created_at == cursor.created_at, Notification.id <= cursor.id),
        )
    )
    db.execute(
        update(Notification)
        .where(
            Notification.id.in_(ids.with_only_columns(Notification.id)),
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC)),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    return redirect_feedback(
        request, "/notifications",
        message(
            'Notifications marked read',
            'Notifications through the selected point are now marked read.',
        ),
    )


@router.post("/{notification_id}/open")
def open_notification(
    request: Request,
    notification_id: UUID,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    notice = service.get_notice(db, user, notification_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="This notification is no longer available.")
    destination = service.card(db, notice)["path"]
    service.mark_read(db, user, [notice.id])
    return redirect_feedback(
        request, destination,
        message(
            'Notification opened',
            'The notification has been marked read.',
        ),
    )


@router.post("/{notification_id}/read")
def read_notification(
    request: Request,
    notification_id: UUID,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    notice = service.get_notice(db, user, notification_id)
    if notice is None:
        raise HTTPException(status_code=404)
    service.mark_read(db, user, [notice.id])
    return redirect_feedback(
        request, "/notifications",
        message(
            'Notification marked read',
            'This notification is now marked read.',
        ),
    )
