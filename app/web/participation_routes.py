"""Member journeys for peer support, welcomes, sessions, invitations and digests."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.community import CommunityTopic
from app.models.participation import DigestPreference, MentorOffer, MentorReport
from app.models.user import User
from app.services import community_participation as participation
from app.services import member_invitations as invitations
from app.services import mentorship, weekly_digest
from app.services.community import (
    CommunityError,
    get_topic_by_slug,
    list_topics,
    set_community_name,
)
from app.services.community_growth import suggested_communities
from app.services.community_sharing import auth_context
from app.web.deps import get_current_user, require_staff, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render
from app.web.urls import page_url

router = APIRouter(tags=["community engagement"])
_actions = FixedWindowLimiter(80, 3600)


async def read_form(request):
    # These flows accept text only. Bound multipart fields and reject file uploads.
    form = await request.form(max_files=0, max_fields=60)
    if any(not isinstance(value, str) for _, value in form.multi_items()):
        raise HTTPException(400, "This form accepts text fields only.")
    return form


def posting_limit(user):
    from app.web.community_routes import _post_limiter, _retry_after

    retry = _retry_after(_post_limiter, user)
    if retry:
        raise HTTPException(
            429,
            "Please wait before publishing another contribution.",
            headers={"Retry-After": str(retry)},
        )


def limit(user):
    key = str(user.id)
    if _actions.is_limited(key):
        raise HTTPException(429, "Please wait before making another community change.")
    _actions.record(key)


def number(form, key, default):
    try:
        return int(form.get(key, default))
    except (TypeError, ValueError):
        raise CommunityError("Choose a valid number.") from None


def page(request, template, user, *, title, error=None, values=None, **context):
    return render(
        request,
        "participation/" + template + ".html",
        {
            "title": title,
            "user": user,
            "error": error,
            "values": values or {},
            **context,
        },
        status_code=400 if error else 200,
    )


def success(request, destination, heading, body):
    return redirect_feedback(request, destination, message(heading, body))


def pagination(request, rows, current):
    return {
        "next_page": page_url(request, page=current + 1) if len(rows) > 20 else None,
        "previous_page": page_url(request, page=current - 1) if current > 1 else None,
    }


@router.get("/mentorship")
def support_directory(
    request: Request,
    topic: str = Query("", max_length=40),
    q: str = Query("", max_length=120),
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        rows = mentorship.directory(db, topic=topic, query=q, page=page_number)
    except CommunityError as exc:
        raise HTTPException(400, str(exc)) from None
    return page(
        request,
        "mentors",
        user,
        title="Find support. Share your experience.",
        cards=rows[:20],
        topics=mentorship.TOPICS,
        selected_topic=topic,
        query=q,
        **pagination(request, rows, page_number),
    )


@router.get("/mentorship/offer")
def offer_form(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return page(
        request,
        "offer",
        user,
        title="Offer peer support",
        topics=mentorship.TOPICS,
        offer=db.get(MentorOffer, user.id),
    )


@router.post("/mentorship/offer")
async def save_offer(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    limit(user)
    form = await read_form(request)
    try:
        mentorship.save_offer(
            db,
            user,
            topics=form.getlist("topics"),
            introduction=form.get("introduction", ""),
            availability=form.get("availability", ""),
            capacity=number(form, "capacity", 3),
            accepting=form.get("accepting") == "on",
            show_completed=form.get("show_completed") == "on",
        )
    except CommunityError as exc:
        db.rollback()
        return page(
            request,
            "offer",
            user,
            title="Offer peer support",
            error=str(exc),
            values={**dict(form), "topics": form.getlist("topics")},
            topics=mentorship.TOPICS,
            offer=db.get(MentorOffer, user.id),
        )
    return success(
        request,
        "/mentorship/offer",
        "Support offer saved",
        "Your availability and public support introduction have been updated.",
    )


@router.get("/mentorship/offers/{identifier}")
def support_form(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    offer = db.get(MentorOffer, identifier)
    account = db.get(User, identifier)
    if (
        not offer
        or not offer.accepting
        or not account
        or not account.is_active
        or account.status != "active"
    ):
        raise HTTPException(404, "This support offer is unavailable.")
    return page(
        request,
        "support_form",
        user,
        title="Ask a colleague for support",
        card=mentorship.offer_card(db, offer, account),
        topics=mentorship.TOPICS,
    )


@router.post("/mentorship/offers/{identifier}")
async def request_support(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    limit(user)
    form = await read_form(request)
    try:
        item = mentorship.request_support(
            db, user, identifier, topic=form.get("topic", ""), goal=form.get("goal", "")
        )
    except CommunityError as exc:
        db.rollback()
        offer = db.get(MentorOffer, identifier)
        account = db.get(User, identifier)
        if not offer or not account:
            raise HTTPException(404, "This support offer is unavailable.") from None
        return page(
            request,
            "support_form",
            user,
            title="Ask a colleague for support",
            error=str(exc),
            values=dict(form),
            topics=mentorship.TOPICS,
            card=mentorship.offer_card(db, offer, account),
        )
    return success(
        request,
        f"/mentorship/requests/{item.id}",
        "Support request saved",
        "Your colleague can review your goal and choose whether to accept.",
    )


@router.get("/mentorship/requests")
def support_requests(
    request: Request,
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    rows = mentorship.requests(db, user, page=page_number)
    return page(
        request,
        "requests",
        user,
        title="My support requests",
        rows=rows[:20],
        topics=mentorship.TOPICS,
        **pagination(request, rows, page_number),
    )


def request_context(db, user, identifier):
    try:
        item = mentorship.owned_request(db, user, identifier)
    except CommunityError:
        raise HTTPException(404, "This support request is unavailable.") from None
    other = db.get(User, item.mentor_id if user.id == item.requester_id else item.requester_id)
    from app.models.community import Connection

    connection = db.get(Connection, item.connection_id) if item.connection_id else None
    return {
        "item": item,
        "other_name": (other.community_name if other else "") or "Colleague",
        "other_id": other.id if other else None,
        "can_message": bool(connection and connection.status == "accepted"),
        "topics": mentorship.TOPICS,
    }


@router.get("/mentorship/requests/{identifier}")
def support_request(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return page(
        request, "request", user, title="Peer support", **request_context(db, user, identifier)
    )


@router.post("/mentorship/requests/{identifier}/{action}")
async def support_action(
    identifier: UUID,
    action: str,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    limit(user)
    form = await read_form(request)
    try:
        if action == "report":
            mentorship.report(
                db, user, identifier, reason=form.get("reason", ""), details=form.get("details", "")
            )
        else:
            mentorship.respond(db, user, identifier, action)
    except CommunityError as exc:
        db.rollback()
        return page(
            request,
            "request",
            user,
            title="Peer support",
            error=str(exc),
            values=dict(form),
            **request_context(db, user, identifier),
        )
    return success(
        request,
        f"/mentorship/requests/{identifier}",
        "Report submitted" if action == "report" else "Support request updated",
        "Staff can review your report."
        if action == "report"
        else "Your saved request status is shown below.",
    )


@router.get("/staff/mentorship-reports")
def support_reports(
    request: Request,
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(MentorReport)
            .where(MentorReport.status == "open")
            .order_by(MentorReport.created_at, MentorReport.id)
            .offset((page_number - 1) * 20)
            .limit(21)
        )
    )
    from app.models.participation import Mentorship

    details = {}
    for report in rows[:20]:
        item = db.get(Mentorship, report.request_id)
        mentor = db.get(User, item.mentor_id) if item else None
        requester = db.get(User, item.requester_id) if item else None
        details[report.id] = {
            "goal": item.goal if item else "Request unavailable",
            "mentor": mentor.community_name if mentor else "Unavailable",
            "requester": requester.community_name if requester else "Unavailable",
        }
    return page(
        request,
        "reports",
        user,
        title="Peer support reports",
        details=details,
        rows=rows[:20],
        **pagination(request, rows, page_number),
    )


@router.post("/staff/mentorship-reports/{identifier}/{action}")
def review_support_report(
    identifier: UUID,
    action: str,
    request: Request,
    user: User = Depends(require_staff),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        mentorship.review_report(db, user, identifier, action)
    except CommunityError as exc:
        raise HTTPException(400, str(exc)) from None
    return success(request, "/staff/mentorship-reports", "Report reviewed", "The review was saved.")


def start_context(db, user):
    return {
        "progress": participation.progress(db, user),
        "goals": participation.GOALS,
        "topics": suggested_communities(db, user),
    }


@router.get("/community/start")
def start(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return page(
        request, "start", user, title="Find your place in nursing", **start_context(db, user)
    )


@router.post("/community/start/preferences")
async def save_start(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    form = await read_form(request)
    try:
        participation.save_journey(
            db,
            user,
            goal=form.get("goal", ""),
            show_recognition=form.get("show_recognition") == "on",
            dismiss=form.get("dismiss") == "yes",
        )
    except CommunityError as exc:
        return page(
            request,
            "start",
            user,
            title="Find your place in nursing",
            error=str(exc),
            values=dict(form),
            **start_context(db, user),
        )
    return success(
        request,
        "/community/start",
        "Your choices are saved",
        "Choose a small next step that is useful to you.",
    )


@router.post("/community/start/introduction")
async def introduction(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    limit(user)
    posting_limit(user)
    form = await read_form(request)
    try:
        if form.get("public_consent") != "on":
            raise CommunityError("Confirm that your introduction will be public.")
        topic_id = UUID(form.get("topic_id", ""))
        if not user.community_name:
            set_community_name(db, user, form.get("community_name", ""))
        post = participation.introduce(db, user, topic_id=topic_id, body=form.get("body", ""))
    except (ValueError, CommunityError) as exc:
        db.rollback()
        return page(
            request,
            "start",
            user,
            title="Find your place in nursing",
            error="Choose a community." if isinstance(exc, ValueError) else str(exc),
            values=dict(form),
            **start_context(db, user),
        )
    return success(
        request,
        f"/posts/{post.id}",
        "Introduction published",
        "Your community host can welcome you, and colleagues can reply.",
    )


@router.get("/communities/{slug}/welcomes")
def welcomes(
    slug: str,
    request: Request,
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    topic = get_topic_by_slug(db, slug)
    if not topic:
        raise HTTPException(404)
    try:
        rows = participation.welcome_queue(db, user, topic, page=page_number)
    except CommunityError as exc:
        raise HTTPException(403, str(exc)) from None
    return page(
        request,
        "welcomes",
        user,
        title="Welcome new colleagues",
        topic=topic,
        rows=rows[:20],
        **pagination(request, rows, page_number),
    )


@router.post("/community/welcomes/{identifier}")
def welcomed(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        participation.acknowledge_welcome(db, user, identifier)
    except CommunityError as exc:
        raise HTTPException(400, str(exc)) from None
    return success(request, f"/posts/{identifier}", "Welcome recorded", "Your welcome is complete.")


def series_context(db, user):
    return {
        "topics": list_topics(db),
        "formats": participation.ACTIVITY_FORMATS,
        "timezones": participation.TIMEZONES,
        "series_id": str(uuid4()),
    }


@router.get("/activities/series/{identifier}/sessions")
def series_sessions(
    identifier: UUID,
    request: Request,
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from app.models.community import CommunityPost, ContentStatus
    from app.models.participation import ActivityOccurrence, ActivitySeries

    series = db.get(ActivitySeries, identifier)
    if not series or not db.get(CommunityTopic, series.topic_id).is_active:
        raise HTTPException(404, "This learning series is unavailable.")
    rows = list(
        db.scalars(
            select(CommunityPost)
            .join(ActivityOccurrence)
            .where(
                ActivityOccurrence.series_id == identifier,
                CommunityPost.status == ContentStatus.PUBLISHED,
            )
            .order_by(ActivityOccurrence.starts_at.desc())
            .offset((page_number - 1) * 20)
            .limit(21)
        )
    )
    return page(
        request,
        "sessions",
        user,
        title=series.title,
        series=series,
        rows=rows[:20],
        **pagination(request, rows, page_number),
    )


@router.get("/activities/series/new")
def series_form(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    return page(
        request,
        "series_form",
        user,
        title="Host a regular learning session",
        **series_context(db, user),
    )


@router.get("/activities/series")
def my_series(
    request: Request,
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    rows = participation.series_list(db, user, page=page_number)
    return page(
        request,
        "series",
        user,
        title="My recurring learning sessions",
        rows=rows[:20],
        **pagination(request, rows, page_number),
    )


@router.post("/activities/series")
async def save_series(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    limit(user)
    posting_limit(user)
    form = await read_form(request)
    try:
        if form.get("public_consent") != "on":
            raise CommunityError("Confirm that this learning series will be public.")
        if not user.community_name:
            set_community_name(db, user, form.get("community_name", ""))
        participation.create_series(
            db,
            user,
            identifier=form.get("series_id", ""),
            topic_id=UUID(form.get("topic_id", "")),
            title=form.get("title", ""),
            instructions=form.get("instructions", ""),
            activity_format=form.get("activity_format", ""),
            starts_at=form.get("starts_at", ""),
            timezone=form.get("timezone", "Africa/Lagos"),
            interval=number(form, "interval", 7),
        )
    except (CommunityError, ValueError) as exc:
        db.rollback()
        return page(
            request,
            "series_form",
            user,
            title="Host a regular learning session",
            error="Choose a community." if isinstance(exc, ValueError) else str(exc),
            values=dict(form),
            **series_context(db, user),
        )
    return success(
        request,
        "/activities/series",
        "Learning series created",
        "The first session is published. Future sessions follow your chosen schedule.",
    )


@router.post("/activities/series/{identifier}/state")
async def series_state(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    form = await read_form(request)
    if form.get("action") not in {"pause", "resume"}:
        raise HTTPException(400, "Choose Pause or Resume.")
    try:
        participation.set_series_active(db, user, identifier, form.get("action") == "resume")
    except CommunityError as exc:
        raise HTTPException(403, str(exc)) from None
    return success(
        request, "/activities/series", "Series updated", "Your schedule choice is saved."
    )


@router.post("/activities/{identifier}/attendance")
async def activity_attendance(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    form = await read_form(request)
    if form.get("action") not in {"join", "leave"}:
        raise HTTPException(400, "Choose Join or Leave.")
    try:
        participation.attendance(db, user, identifier, attending=form.get("action") == "join")
    except CommunityError as exc:
        raise HTTPException(400, str(exc)) from None
    return success(
        request,
        f"/posts/{identifier}",
        "Activity choice saved",
        "Your choice is private. Following discussion replies is controlled separately.",
    )


def invitation_context(db, user, request, current=1):
    rows = invitations.summaries(db, user, page=current)
    return {"rows": rows[:20], "topics": list_topics(db), **pagination(request, rows, current)}


@router.get("/invitations")
def my_invitations(
    request: Request,
    page_number: int = Query(1, alias="page", ge=1, le=10000),
    destination: str = Query("", max_length=240),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return page(
        request,
        "invitations",
        user,
        title="Bring colleagues into your community",
        values={"destination": destination},
        **invitation_context(db, user, request, page_number),
    )


@router.post("/invitations")
async def create_invitation(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    limit(user)
    form = await read_form(request)
    try:
        invitations.create_invitation(
            db, user, destination=form.get("destination", ""), label=form.get("label", "")
        )
    except CommunityError as exc:
        db.rollback()
        return page(
            request,
            "invitations",
            user,
            title="Bring colleagues into your community",
            error=str(exc),
            values=dict(form),
            **invitation_context(db, user, request),
        )
    return success(
        request, "/invitations", "Invitation ready", "Share its link when you are ready."
    )


@router.post("/invitations/{identifier}/revoke")
def revoke_invitation(
    identifier: UUID,
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        invitations.revoke(db, user, identifier)
    except CommunityError as exc:
        raise HTTPException(404, str(exc)) from None
    return success(
        request, "/invitations", "Invitation revoked", "This link no longer accepts visits."
    )


@router.get("/invite/{token}")
def invitation_landing(
    token: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = invitations.resolve(db, token)
    if not item:
        raise HTTPException(404, "This invitation has expired or is unavailable.")
    invitations.record_visit(db, request, item, token)
    return page(
        request,
        "invitation",
        user,
        title="You are invited to Nurse.ng",
        destination=item.destination,
        **auth_context(db, item.destination),
    )


def digest_context(db, user):
    pref = db.get(DigestPreference, user.id)
    return {
        "preference": pref,
        "timezones": participation.TIMEZONES,
        "preview": weekly_digest.highlights(db, user, pref) if pref else [],
    }


@router.get("/digest")
def digest_form(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    return page(
        request, "digest", user, title="Your weekly community digest", **digest_context(db, user)
    )


@router.post("/digest")
async def save_digest(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    form = await read_form(request)
    try:
        weekly_digest.save_preferences(
            db,
            user,
            enabled=form.get("enabled") == "on",
            questions=form.get("questions") == "on",
            activities=form.get("activities") == "on",
            opportunities=form.get("opportunities") == "on",
            weekday=number(form, "weekday", 0),
            timezone=form.get("timezone", "Africa/Lagos"),
        )
    except CommunityError as exc:
        db.rollback()
        return page(
            request,
            "digest",
            user,
            title="Your weekly community digest",
            error=str(exc),
            values=dict(form),
            **digest_context(db, user),
        )
    return success(
        request, "/digest", "Digest preferences saved", "Your weekly email choice is saved."
    )


@router.get("/digest/unsubscribe/{identifier}/{token}")
def unsubscribe_form(identifier: UUID, token: str, request: Request, db: Session = Depends(get_db)):
    import hmac

    pref = db.get(DigestPreference, identifier)
    if not pref or not hmac.compare_digest(token, weekly_digest.unsubscribe_token(pref)):
        raise HTTPException(404, "This unsubscribe link is unavailable.")
    return page(
        request,
        "unsubscribe",
        None,
        title="Turn off your weekly digest",
        unsubscribe_action=request.url.path,
        disabled=not pref.enabled,
    )


@router.post("/digest/unsubscribe/{identifier}/{token}")
def unsubscribe(identifier: UUID, token: str, request: Request, db: Session = Depends(get_db)):
    # A purpose-bound signed token authorizes only disabling this subscription.
    if not weekly_digest.unsubscribe(db, identifier, token):
        raise HTTPException(404, "This unsubscribe link is unavailable.")
    return page(
        request,
        "unsubscribe",
        None,
        title="Weekly digest turned off",
        unsubscribe_action=request.url.path,
        disabled=True,
    )
