"""Classroom access, host moderation and authenticated media-provider callbacks.

Browser mutations use the signed-in account and a CSRF header. Provider events
use raw-body JWT verification instead: they have no browser session. Both enter
the same education domain so a client cannot claim attendance, grant itself a
host role, or mark a recording complete. External calls run in a worker thread
and use bounded timeouts; they must not block the ASGI event loop.

Session row locks serialize starts, recording requests and permission changes
on PostgreSQL. Calls create/update the provider room before committing the
matching application state. A provider failure therefore remains visible and
does not produce a fictitious live/recording success state.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.models.education import (
    EducatorProfile,
    LearningAttendance,
    LearningRecording,
    LearningSession,
    SessionMessage,
    SessionRegistration,
)
from app.models.user import User, UserStatus
from app.services import education, education_live
from app.web.deps import require_user, verify_csrf
from app.web.education_common import (
    PREFIX,
    bounded_body,
    classroom_json,
    identifier,
    learning_page,
    session_context,
)
from app.web.feedback import message, redirect_feedback

router = APIRouter(tags=["live classrooms"])


def _lock_educator(db, educator_id):
    """Serialize room grants and approval changes before taking session locks.

    The existing account is a lock target even for a first educator application.
    PostgreSQL locks account, profile and session in that order. SQLite takes its
    writer lock through a no-op account update because FOR UPDATE is ignored.
    A review retains these locks through closure and the final approval change.
    """
    if db.get_bind().dialect.name == "sqlite":
        try:
            db.execute(
                update(User)
                .where(User.id == educator_id)
                .values(id=User.id, updated_at=User.updated_at)
                .execution_options(synchronize_session=False)
            )
        except OperationalError:
            db.rollback()
            raise education.EducationError(
                "The learning service is busy. Retry this action in a moment.", 503
            ) from None
    db.scalar(
        select(User)
        .where(User.id == educator_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return db.scalar(
        select(EducatorProfile)
        .where(EducatorProfile.user_id == educator_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _lock_session(db, session_id):
    """Acquire educator then session locks before token/host/recording actions."""
    educator_id = db.scalar(
        select(LearningSession.educator_id).where(LearningSession.id == session_id)
    )
    if educator_id is not None:
        _lock_educator(db, educator_id)
    return db.scalar(
        select(LearningSession)
        .where(LearningSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _host(db, user, session_id):
    """An approved owner or active staff moderator may manage this specific room."""
    session = education.get_session(db, session_id, user=user)
    if not education.can_manage_session(db, user, session):
        raise education.EducationError(
            "Only this lecture's educator can manage the classroom.", 403
        )
    return session


def _participant_view(db, user, session_id):
    """Permit a waiting-room/history view without granting a live media token."""
    session = education.get_session(db, session_id, user=user)
    # The domain's participant-only history check also rechecks course enrollment.
    education.session_messages(db, user, session_id, limit=1)
    return session


def _display_name(db, session, user):
    """Use deliberately public identities, never the account's private full name."""
    if user.id == session.educator_id:
        return session.educator.display_name
    return user.community_name or ("Moderator" if user.is_staff else "Learner")


@router.get(PREFIX + "/sessions/{session_id}/room")
def classroom(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Show prejoin controls only after current reservation/hosting access is checked."""
    session = _participant_view(db, user, session_id)
    return learning_page(request, "room", user, **session_context(db, session, user))


def _token(db, user, session_id, payload):
    _lock_session(db, session_id)
    access = education.join_session(db, user, session_id)
    session = access["session"]
    if session.recording_enabled and payload.get("recording_consent") is not True:
        raise education.EducationError(
            "Acknowledge the recording notice before joining this lecture."
        )
    result = education_live.participant_token(
        session_id,
        user,
        is_host=access["role"] == "host",
        can_speak=access["can_publish"],
        session_format=session.session_format,
        display_name=_display_name(db, session, user),
    )
    db.commit()  # Release the lifecycle lock only after the room grant is issued.
    return result


@router.post(PREFIX + "/sessions/{session_id}/token")
async def classroom_token(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Issue a short-lived, room-scoped grant after authorization and explicit consent."""
    payload = await classroom_json(request)
    result = await run_in_threadpool(_token, db, user, session_id, payload)
    return JSONResponse(
        result, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    )


@router.get(PREFIX + "/sessions/{session_id}/room-state")
def classroom_state(
    session_id: UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Return participant-only state, with presence derived from signed provider evidence."""
    session = _participant_view(db, user, session_id)
    active_ids = set(
        db.scalars(
            select(LearningAttendance.user_id).where(
                LearningAttendance.session_id == session_id,
                LearningAttendance.left_at.is_(None),
            )
        )
    )
    registrations = {
        row.user_id: row
        for row in db.scalars(
            select(SessionRegistration).where(
                SessionRegistration.session_id == session_id,
                SessionRegistration.status == "reserved",
            )
        )
    }
    participants = []
    for account in db.scalars(
        select(User).where(
            User.id.in_(active_ids), User.is_active.is_(True), User.status == UserStatus.ACTIVE
        )
    ):
        registration = registrations.get(account.id)
        host = education.can_manage_session(db, account, session)
        if not host and not registration:
            continue
        participants.append(
            {
                "identity": str(account.id),
                "display_name": _display_name(db, session, account),
                "is_host": host,
                "can_speak": host or bool(registration and registration.speaker_allowed),
                "hand_raised": bool(registration and registration.hand_raised_at),
            }
        )
    messages = []
    for row in education.session_messages(db, user, session_id):
        account = db.get(User, row.user_id) if row.user_id else None
        name = _display_name(db, session, account) if account else "Former member"
        messages.append(
            {
                "id": str(row.id),
                "display_name": name,
                "kind": row.kind,
                "body": row.body,
                "created_at": education.utc(row.created_at).isoformat(),
                "answered": bool(row.answered_at),
                "answer": row.answer,
            }
        )
    return JSONResponse(
        {
            "status": session.status,
            "participants": participants,
            "messages": messages,
            "recording": bool(
                db.scalar(
                    select(LearningRecording.id)
                    .where(
                        LearningRecording.session_id == session_id,
                        LearningRecording.status.in_(["starting", "recording", "ending"]),
                    )
                    .limit(1)
                )
            ),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post(PREFIX + "/sessions/{session_id}/messages")
async def classroom_message(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Persist a plain-text contribution after participant access/rate-limit checks."""
    payload = await classroom_json(request)
    if not isinstance(payload.get("body", ""), str) or not isinstance(
        payload.get("kind", "question"), str
    ):
        raise HTTPException(400, "Enter a text question or chat message.")
    row = await run_in_threadpool(
        education.send_session_message,
        db,
        user,
        session_id,
        payload.get("body", ""),
        payload.get("kind", "question"),
    )
    return JSONResponse({"id": str(row.id)}, status_code=201, headers={"Cache-Control": "no-store"})


@router.post(PREFIX + "/sessions/{session_id}/hand")
async def classroom_hand(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """A learner requests speaking time; the request grants no publishing permission."""
    payload = await classroom_json(request)
    if not isinstance(payload.get("raised"), bool):
        raise HTTPException(400, "Choose whether to raise or lower your hand.")
    row = await run_in_threadpool(education.set_hand_raise, db, user, session_id, payload["raised"])
    return JSONResponse({"raised": bool(row.hand_raised_at)}, headers={"Cache-Control": "no-store"})


def _moderate(db, user, session_id, payload):
    _lock_session(db, session_id)
    _host(db, user, session_id)
    action = payload.get("action")
    if not isinstance(action, str):
        raise education.EducationError("Choose a supported classroom moderation action.")
    if action in {"answer", "remove_message"}:
        if action == "answer" and not isinstance(payload.get("answer", ""), str):
            raise education.EducationError("Enter a text answer to this question.")
        message_id = identifier(payload.get("message_id"))
        row = db.get(SessionMessage, message_id)
        if not row or row.session_id != session_id:
            raise education.EducationError("This question belongs to another classroom.", 404)
        education.moderate_message(
            db,
            user,
            message_id,
            "answer" if action == "answer" else "hide",
            answer=payload.get("answer", "Answered during the lecture."),
        )
    elif action in {"mute", "remove", "allow_speaking", "revoke_speaking"}:
        target = identifier(payload.get("identity"))
        registration = db.get(SessionRegistration, (session_id, target))
        if not registration or registration.status != "reserved":
            raise education.EducationError("This learner is not registered in this classroom.", 404)
        education_live.moderate_participant(session_id, target, action=action)
        if action != "mute":
            education.moderate_participant(db, user, session_id, target, action)
        else:
            db.commit()
    else:
        raise education.EducationError("Choose a supported classroom moderation action.")
    return {"ok": True}


@router.post(PREFIX + "/sessions/{session_id}/moderation")
async def classroom_moderation(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Apply host controls to this room's exact participant/message, then retain history."""
    payload = await classroom_json(request)
    result = await run_in_threadpool(_moderate, db, user, session_id, payload)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


def _transition(db, user, session_id, state, *, commit=True):
    """Close/open provider media before retaining the matching classroom state.

    Educator revocations use ``commit=False`` for ended sessions so the caller
    retains its educator lock across every closure and the final profile change.
    Other lifecycle notices keep their ordinary committed outbox behavior.
    """
    _lock_session(db, session_id)
    session = _host(db, user, session_id)
    recipients = list(
        db.scalars(
            select(SessionRegistration.user_id).where(
                SessionRegistration.session_id == session_id,
                SessionRegistration.status == "reserved",
            )
        )
    )
    now = datetime.now(UTC)
    if state == "live" and session.status != "live":
        # Staff can moderate a paused educator's history but must not create a
        # remote room that the domain would subsequently refuse to open.
        if not education.can_teach(db, db.get(User, session.educator_id)):
            raise education.EducationError("The session educator must currently be approved.")
        if session.course and session.course.status != "published":
            raise education.EducationError("Publish the associated course before opening its room.")
        if session.status != "scheduled" or education.utc(session.ends_at) <= now:
            raise education.EducationError("Only a scheduled, current lecture can be opened.")
        if now < education.utc(session.starts_at) - timedelta(minutes=15):
            raise education.EducationError(
                "The classroom can open fifteen minutes before its scheduled start."
            )
        education_live.create_room(session_id, max_participants=min(1000, session.capacity + 1))
    elif state in {"ended", "cancelled"} and session.status == "live":
        education_live.delete_room(session_id)
    result = education.change_session_state(db, user, session_id, state, commit=commit)
    from app.services.education_notifications import notify_session_change

    notify_session_change(db, result, recipients, state)
    return result


@router.post(PREFIX + "/sessions/{session_id}/start", dependencies=[Depends(verify_csrf)])
async def start_classroom(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """The provider must accept room creation before the lecture becomes live."""
    await run_in_threadpool(_transition, db, user, session_id, "live")
    return redirect_feedback(
        request,
        f"{PREFIX}/sessions/{session_id}/room",
        message("Classroom opened", "Your lecture is live. Join when you are ready."),
    )


@router.post(PREFIX + "/sessions/{session_id}/end", dependencies=[Depends(verify_csrf)])
async def end_classroom(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Disconnect the media room before closing the application session."""
    await run_in_threadpool(_transition, db, user, session_id, "ended")
    return redirect_feedback(
        request,
        f"{PREFIX}/sessions/{session_id}",
        message("Lecture ended", "The classroom is closed. Recording processing may continue."),
    )


@router.post(PREFIX + "/sessions/{session_id}/cancel", dependencies=[Depends(verify_csrf)])
async def cancel_classroom(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Cancel the schedule and release reservations after any live room is closed."""
    await run_in_threadpool(_transition, db, user, session_id, "cancelled")
    return redirect_feedback(
        request,
        f"{PREFIX}/sessions/{session_id}",
        message("Lecture cancelled", "Registered learners will see the cancellation notice."),
    )


def _record(db, user, session_id, stop):
    _lock_session(db, session_id)
    session = _host(db, user, session_id)
    if session.status != "live" or not session.recording_enabled:
        raise education.EducationError("Recording must be enabled for a live classroom.")
    active = db.scalar(
        select(LearningRecording)
        .where(
            LearningRecording.session_id == session_id,
            LearningRecording.status.in_(["starting", "recording", "ending"]),
        )
        .limit(1)
    )
    if stop:
        if active:
            education_live.stop_recording(active.provider_egress_id)
            active.status = "ending"
            db.commit()
        else:
            db.commit()
    elif not active:
        result = education_live.start_recording(session_id)
        education.register_recording(db, user, session_id, result)
    else:
        db.commit()


@router.post(PREFIX + "/sessions/{session_id}/recording", dependencies=[Depends(verify_csrf)])
async def classroom_recording(
    session_id: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Request private egress; only its verified callback may mark playback complete."""
    values = dict(await request.form())
    if values.get("action") not in {"start", "stop"}:
        raise education.EducationError("Choose Start recording or Stop recording.")
    stop = values["action"] == "stop"
    await run_in_threadpool(_record, db, user, session_id, stop)
    return redirect_feedback(
        request,
        f"{PREFIX}/sessions/{session_id}",
        message(
            "Recording request accepted",
            "The recording status will update when the media service confirms it.",
        ),
    )


@router.get(PREFIX + "/recordings/{recording_id}")
def recording_playback(
    recording_id: UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Recheck learner access before issuing a short-lived private storage URL."""
    recording = education.recording_for(db, user, recording_id)
    url = education_live.recording_download_url(
        recording.storage_key, session_id=recording.session_id
    )
    return RedirectResponse(
        url,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post(PREFIX + "/webhooks/livekit")
async def classroom_webhook(request: Request, db: Session = Depends(get_db)):
    """Verify exact provider bytes before normalizing and applying a replay-safe event."""
    body = await bounded_body(request, education_live.MAX_PROVIDER_BYTES)
    try:
        event = education_live.verify_webhook(body, request.headers.get("Authorization", ""))
        normalized = education_live.normalize_provider_event(event)
        if normalized is not None:
            await run_in_threadpool(education.apply_provider_event, db, **normalized)
    except education_live.EducationLiveError as error:
        raise HTTPException(401, str(error)) from None
    return JSONResponse({"received": True}, headers={"Cache-Control": "no-store"})
