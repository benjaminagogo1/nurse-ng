"""Community membership, learning feeds, helpful answers and public invitations."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.user import User
from app.services import community_growth as growth
from app.services.community import (
    CommunityError,
    get_topic_by_slug,
    reply_page_number,
    set_community_name,
)
from app.services.community_sharing import invitation_destination
from app.services.member_interests import INTEREST_OPTIONS
from app.web.community_routes import _listing_context
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render
from app.web.urls import page_url

router = APIRouter(tags=["community participation"])
_creation_limit = FixedWindowLimiter(3, 3600)


@router.get("/topics")
@router.get("/communities")
def community_directory(
    request: Request,
    q: str = Query("", max_length=120),
    interest: str = Query("", max_length=80),
    mine: bool = False,
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = growth.communities(db, query=q, interest=interest, user=user, mine=mine, page=page)
    return render(
        request,
        "community/communities.html",
        {
            "title": "Find your communities",
            "user": user,
            "topics": rows[:20],
            "community_summaries": growth.community_summaries(db, rows[:20], user),
            "search_query": q,
            "selected_interest": interest,
            "mine": mine,
            "interest_options": INTEREST_OPTIONS,
            "community_examples": growth.COMMUNITY_EXAMPLES,
            "page_number": page,
            "next_page": page_url(request, page=page + 1)
            if len(rows) > 20
            else None,
            "previous_page": page_url(request, page=page - 1)
            if page > 1
            else None,
        },
        headers={"Cache-Control": "no-store"},
    )


def _form(request, db, user, *, topic=None, values=None, error=None, code=200):
    return render(
        request,
        "community/community_form.html",
        {
            "title": "Edit community" if topic else "Create a community",
            "user": user,
            "topic": topic,
            "values": values
            or (
                {
                    key: getattr(topic, key)
                    for key in ("name", "description", "welcome_text", "rules", "interest")
                }
                if topic
                else {}
            ),
            "error": error,
            "interest_options": INTEREST_OPTIONS,
            "community_examples": growth.COMMUNITY_EXAMPLES,
        },
        status_code=code,
    )


@router.get("/communities/new")
def new_community(
    request: Request,
    example: str = Query("", max_length=40),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return _form(request, db, user, values=growth.COMMUNITY_EXAMPLES.get(example, {}).copy())


@router.post("/communities")
def add_community(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    welcome_text: str = Form(""),
    rules: str = Form(""),
    interest: str = Form(""),
    community_name: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    values = dict(
        name=name,
        description=description,
        welcome_text=welcome_text,
        rules=rules,
        interest=interest,
    )
    key = str(user.id)
    if _creation_limit.is_limited(key):
        return _form(
            request,
            db,
            user,
            values={**values, "community_name": community_name},
            error="Please wait before creating another community.",
            code=429,
        )
    _creation_limit.record(key)
    try:
        if not user.community_name and community_name.strip():
            set_community_name(db, user, community_name)
        topic = growth.create_community(db, user, **values)
    except CommunityError as exc:
        db.rollback()
        return _form(
            request,
            db,
            user,
            values={**values, "community_name": community_name},
            error=str(exc),
            code=400,
        )
    return redirect_feedback(
        request,
        f"/topics/{topic.slug}",
        message("Community created", "Welcome your colleagues and start the first conversation."),
    )


def _topic(db, slug):
    topic = get_topic_by_slug(db, slug)
    if topic is None:
        raise HTTPException(404, "This community is unavailable.")
    return topic


@router.get("/communities/{slug}/edit")
def edit_community(
    slug: str, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    topic = _topic(db, slug)
    if not growth.can_manage_community(user, topic):
        raise HTTPException(403, "Only the host or staff can edit this community.")
    return _form(request, db, user, topic=topic)


@router.post("/communities/{slug}/edit")
def save_community(
    slug: str,
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    welcome_text: str = Form(""),
    rules: str = Form(""),
    interest: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    topic = _topic(db, slug)
    if not growth.can_manage_community(user, topic):
        raise HTTPException(403, "Only the host or staff can edit this community.")
    values = dict(
        name=name,
        description=description,
        welcome_text=welcome_text,
        rules=rules,
        interest=interest,
    )
    try:
        growth.update_community(db, user, topic, **values)
    except CommunityError as exc:
        return _form(request, db, user, topic=topic, values=values, error=str(exc), code=400)
    return redirect_feedback(
        request,
        f"/topics/{topic.slug}",
        message("Community updated", "Your community details were saved."),
    )


@router.get("/communities/{slug}")
def community_link(slug: str, db: Session = Depends(get_db)):
    topic = _topic(db, slug)
    return RedirectResponse(f"/topics/{topic.slug}", 303)


@router.post("/communities/{slug}/membership")
def join_community(
    slug: str,
    request: Request,
    action: str = Form("join"),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    if action not in {"join", "leave"}:
        raise HTTPException(400, "Choose Join or Leave.")
    topic = _topic(db, slug)
    try:
        growth.membership(db, user, topic, joined=action == "join")
    except CommunityError as exc:
        raise HTTPException(400, str(exc)) from None
    return redirect_feedback(
        request,
        f"/topics/{topic.slug}",
        message(
            "Community joined" if action == "join" else "Community left",
            "Find its conversations in My communities."
            if action == "join"
            else "You can still read its public conversations.",
            compact=True,
        ),
    )


@router.get("/feed/communities")
def joined_feed(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return render(
        request,
        "community/feed.html",
        {
            "title": "My communities",
            "user": user,
            "feed_view": "communities",
            **_listing_context(request, db, user, q, page, community_member_id=user.id),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/feed/unanswered")
def unanswered_feed(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return render(
        request,
        "community/feed.html",
        {
            "title": "Questions needing replies",
            "user": user,
            "feed_view": "unanswered",
            **_listing_context(request, db, user, q, page, unanswered=True),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/activities")
def activities(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return render(
        request,
        "community/feed.html",
        {
            "title": "Learning together",
            "user": user,
            "feed_view": "activities",
            **_listing_context(request, db, user, q, page, post_kind="activity"),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/replies/{reply_id}/helpful")
def helpful(
    reply_id: UUID,
    request: Request,
    action: str = Form("mark"),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    if action not in {"mark", "remove"}:
        raise HTTPException(400, "Choose a valid helpful action.")
    try:
        reply = growth.recognize_reply(db, user, reply_id, marked=action == "mark")
    except CommunityError as exc:
        raise HTTPException(400, str(exc)) from None
    page = reply_page_number(db, reply)
    return redirect_feedback(
        request,
        f"/posts/{reply.post_id}?page={page}#reply-{reply.id}",
        message("Recognition saved", "Your helpful choice was saved.", compact=True),
    )


@router.post("/replies/{reply_id}/answer")
def answer(
    reply_id: UUID,
    request: Request,
    action: str = Form("select"),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    if action not in {"select", "remove"}:
        raise HTTPException(400, "Choose a valid answer action.")
    try:
        reply = growth.select_answer(db, user, reply_id, selected=action == "select")
    except CommunityError as exc:
        raise HTTPException(403, str(exc)) from None
    page = reply_page_number(db, reply)
    return redirect_feedback(
        request,
        f"/posts/{reply.post_id}?page={page}#reply-{reply.id}",
        message("Answer updated", "Your question's answer was updated.", compact=True),
    )


@router.get("/join/{token}")
def public_invitation(token: str, db: Session = Depends(get_db)):
    target = invitation_destination(db, token)
    if not target:
        raise HTTPException(404, "This invitation is no longer available.")
    return RedirectResponse(target, 303, headers={"Cache-Control": "no-store"})
