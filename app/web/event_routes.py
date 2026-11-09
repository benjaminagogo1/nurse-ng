"""Staff publishing, member RSVPs, and public event details."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.events import CommunityEvent, EventAttendance
from app.models.user import User
from app.services.events import calendar, local_time, upcoming, validated
from app.web.deps import get_current_user, require_staff, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/events", tags=["events"])


def load_event(db, event_id):
    event = db.get(CommunityEvent, event_id)
    if event is None:
        raise HTTPException(404, "This event is no longer available.")
    return event


@router.get("")
def index(
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = upcoming(db, 26, (page - 1) * 25)
    return render(
        request,
        "events/index.html",
        {
            "user": user,
            "events": rows[:25],
            "more": len(rows) > 25,
            "page_number": page,
            "local_time": local_time,
        },
    )


@router.get("/new")
def new(request: Request, user: User = Depends(require_staff)):
    return render(request, "events/form.html", {"user": user, "event": None, "values": {}})


@router.post("")
async def create(
    request: Request,
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    values = dict(await request.form())
    try:
        fields = validated(values)
    except ValueError as exc:
        return render(
            request,
            "events/form.html",
            {
                "user": user,
                "event": None,
                "values": values,
                "error": str(exc),
            },
            400,
        )
    event = CommunityEvent(**fields, creator_id=user.id)
    db.add(event)
    db.commit()
    return redirect_feedback(
        request,
        f"/events/{event.id}",
        message(
            "Event published",
            "Members can now view the event and RSVP.",
        ),
    )


@router.get("/{event_id}/edit")
def edit(
    event_id: UUID,
    request: Request,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    values = {
        key: getattr(event, key)
        for key in (
            "title",
            "description",
            "location",
            "registration_url",
        )
    }
    values.update(
        {
            key: local_time(getattr(event, key)).strftime("%Y-%m-%dT%H:%M")
            for key in ("starts_at", "ends_at")
        }
    )
    return render(request, "events/form.html", {"user": user, "event": event, "values": values})


@router.post("/{event_id}/edit")
async def update(
    event_id: UUID,
    request: Request,
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    values = dict(await request.form())
    if event.status == "cancelled":
        raise HTTPException(
            400, "A cancelled event cannot be changed. Publish a new event instead."
        )
    try:
        fields = validated(values)
    except ValueError as exc:
        return render(
            request,
            "events/form.html",
            {
                "user": user,
                "event": event,
                "values": values,
                "error": str(exc),
            },
            400,
        )
    for key, value in fields.items():
        setattr(event, key, value)
    db.commit()
    return redirect_feedback(
        request,
        f"/events/{event.id}",
        message(
            "Event updated",
            "The updated details are now visible. Check this page before travelling.",
        ),
    )


@router.post("/{event_id}/cancel")
def cancel(
    event_id: UUID,
    request: Request,
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    event.status = "cancelled"
    db.commit()
    return redirect_feedback(
        request,
        f"/events/{event.id}",
        message(
            "Event cancelled",
            "The event is marked cancelled and no longer accepts RSVPs.",
        ),
    )


@router.post("/{event_id}/rsvp")
def rsvp(
    event_id: UUID,
    request: Request,
    attending: bool = Form(...),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    if attending:
        if event.status != "scheduled" or local_time(event.ends_at) <= datetime.now(UTC):
            raise HTTPException(400, "This event is cancelled or has ended. RSVPs are closed.")
        if db.get(EventAttendance, (event.id, user.id)) is None:
            db.add(EventAttendance(event_id=event.id, user_id=user.id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if db.get(EventAttendance, (event.id, user.id)) is None:
                    raise
    else:
        db.execute(
            delete(EventAttendance).where(
                EventAttendance.event_id == event.id,
                EventAttendance.user_id == user.id,
            )
        )
        db.commit()
    return redirect_feedback(
        request,
        f"/events/{event.id}",
        message(
            "RSVP saved" if attending else "RSVP cancelled",
            "Your choice has been saved. Check the event details for registration requirements.",
        ),
    )


@router.get("/{event_id}/calendar.ics")
def download(event_id: UUID, db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    return Response(
        calendar(event),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="nurse-ng-event.ics"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{event_id}")
def detail(
    event_id: UUID,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    return render(
        request,
        "events/show.html",
        {
            "user": user,
            "event": event,
            "local_time": local_time,
            "attending": bool(user and db.get(EventAttendance, (event.id, user.id))),
            "count": db.scalar(
                select(func.count())
                .select_from(EventAttendance)
                .where(
                    EventAttendance.event_id == event.id,
                )
            ),
            "ended": local_time(event.ends_at) <= datetime.now(UTC),
        },
    )
