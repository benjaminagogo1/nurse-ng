"""Public community pages and authenticated participation actions."""

import uuid
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.community_storage import CommunityStorageError, community_media_path
from app.core.config import settings
from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.community import CommunityReply, Connection, ConnectionStatus, ContentStatus
from app.models.profile import NurseProfile, ProfileStatus
from app.models.reels import Reel
from app.models.user import User
from app.services import community_growth as growth
from app.services.community import (
    REPORT_REASON_LABELS,
    CommunityError,
    CommunityUpload,
    add_reply,
    connection_between,
    create_post,
    discussion_reply_page,
    discussion_summaries,
    first_unread_reply,
    follow_discussion,
    follow_exists,
    follow_profile,
    followed_user_ids,
    get_public_media,
    get_published_post,
    get_topic_by_slug,
    list_connections,
    list_published_posts,
    list_received_requests,
    list_topics,
    mark_discussion_read,
    public_profile_ids,
    remove_connection,
    reply_page_number,
    reply_references,
    report_post,
    report_reply,
    request_connection,
    respond_to_connection,
    set_community_name,
    unfollow_discussion,
    unfollow_profile,
    users_by_id,
)
from app.services.community_sharing import auth_context, invitation_url, share_preview
from app.services.member_interests import INTEREST_OPTIONS
from app.services.profiles import (
    PROFESSIONAL_STATUS_LABELS,
    count_discoverable_profiles,
    get_active_profile_by_public_id,
    list_discoverable_profiles,
    public_profile_fields,
)
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import confirm_published_draft, render
from app.web.urls import page_url

router = APIRouter(tags=["community"])

_post_limiter = FixedWindowLimiter(
    settings.community_post_limit,
    settings.community_post_window_seconds,
)
_reply_limiter = FixedWindowLimiter(
    settings.community_reply_limit,
    settings.community_reply_window_seconds,
)
_report_limiter = FixedWindowLimiter(
    settings.community_report_limit,
    settings.community_report_window_seconds,
)


def _identifier(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None


def _post_context(
    db: Session,
    posts: list,
    user: User | None = None,
) -> dict[str, object]:
    from app.services.community_participation import recognition_summaries

    author_ids = {post.author_id for post in posts}
    return {
        "posts": posts,
        "recognition_summaries": recognition_summaries(db, author_ids),
        "profile_ids": public_profile_ids(db, author_ids),
        "summaries": discussion_summaries(db, posts, user),
        "answer_summaries": growth.answer_summaries(db, posts),
        "post_kind_labels": growth.POST_KINDS,
        "activity_formats": growth.ACTIVITY_FORMATS,
        "post_share_urls": {post.id: invitation_url(f"/posts/{post.id}") for post in posts},
    }


def _listing_context(request: Request, db: Session, user: User | None,
                     query: str, page_number: int, **filters) -> dict[str, object]:
    page_size = 20
    query = query.strip()
    posts = list_published_posts(
        db, query=query, offset=(page_number - 1) * page_size, limit=page_size + 1, **filters,
    )
    return {
        **_post_context(db, posts[:page_size], user),
        "search_query": query,
        "listing_path": request.url.path,
        "page_number": page_number,
        "next_page": page_url(request, page=page_number + 1)
        if len(posts) > page_size else None,
        "previous_page": page_url(request, page=page_number - 1)
        if page_number > 1 else None,
    }


def _conversation_context(
    db: Session, post, user: User | None, *, page_number: int = 1,
    reply_to: str = "", reply_target_explicit: bool = False, **extra,
) -> dict[str, object]:
    reply_page = discussion_reply_page(db, post, user, page=page_number)
    target_ids = {reply.in_reply_to_id for reply in reply_page.replies if reply.in_reply_to_id}
    selected = None
    if reply_to:
        try:
            selected = uuid.UUID(reply_to)
            target_ids.add(selected)
        except ValueError:
            pass
    references = reply_references(db, post.id, target_ids)
    from app.services.community_participation import activity_details, recognition_summaries

    return {
        "title": f"Conversation in {post.topic.name}", "user": user, "post": post,
        "conversation_detail": True,
        "activity_participation": activity_details(db, post, user),
        "recognition_summaries": recognition_summaries(
            db, {post.author_id, *(reply.author_id for reply in reply_page.replies)}),
        "reply_page": reply_page,
        "reply_references": references,
        "reply_target": references.get(selected),
        "reply_target_id": str(selected) if selected else reply_to,
        "reply_target_explicit": reply_target_explicit,
        "summaries": discussion_summaries(db, [post], user),
        "profile_ids": public_profile_ids(
            db, {post.author_id, *(reply.author_id for reply in reply_page.replies)},
        ),
        "report_reasons": REPORT_REASON_LABELS.items(),
        "answer_summaries": growth.answer_summaries(db, [post]),
        "helpful_summaries": growth.helpful_summaries(db, reply_page.replies, user),
        "post_kind_labels": growth.POST_KINDS, "activity_formats": growth.ACTIVITY_FORMATS,
        "post_share_urls": {post.id: invitation_url(f"/posts/{post.id}")},
        **auth_context(db, f"/posts/{post.id}#reply-form"),
        **share_preview(f"/posts/{post.id}", post.title or f"Conversation in {post.topic.name}",
                        post.body or "Join this public nursing conversation on Nurse.ng."),
        **extra,
    }


def _new_post_context(
    db: Session,
    *,
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> dict[str, object]:
    topics = list_topics(db)
    return {
        "title": "Ask or share",
        "topics": topics,
        "values": values
        or {"topic_id": "", "body": "",
            "external_video_url": "", "community_name": ""},
        "error": error,
        "post_kind_labels": growth.POST_KINDS,
        "activity_formats": growth.ACTIVITY_FORMATS,
        "image_max_mb": max(1, settings.community_image_max_bytes // (1024 * 1024)),
        "video_max_mb": max(1, settings.community_video_max_bytes // (1024 * 1024)),
        "video_max_minutes": max(1, settings.community_video_max_seconds // 60),
        "daily_upload_mb": max(
            1, settings.community_upload_window_bytes // (1024 * 1024)
        ),
        "storage_quota_gb": max(
            1, settings.community_storage_quota_bytes // (1024 * 1024 * 1024)
        ),
    }


def _stream_upload(upload: UploadFile) -> CommunityUpload:
    return CommunityUpload(
        file=upload.file,
        filename=upload.filename or "",
    )


def _retry_after(limiter: FixedWindowLimiter, user: User) -> int:
    key = str(user.id)
    if limiter.is_limited(key):
        return limiter.retry_after(key)
    limiter.record(key)
    return 0


def _raise_rate_limited(retry_after: int, message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=message,
        headers={"Retry-After": str(retry_after)},
    )


def _public_profile(db: Session, public_id: str) -> NurseProfile:
    profile = get_active_profile_by_public_id(db, _identifier(public_id))
    if profile is None or not profile.discoverable:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return profile


@router.get("/feed")
def feed(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    return render(
        request,
        "community/feed.html",
        {
            "title": "Community conversations",
            "user": user,
            "feed_view": "all",
            **_listing_context(request, db, user, q, page),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/feed/following")
def following_feed(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    return render(
        request,
        "community/feed.html",
        {
            "title": "Following feed",
            "user": user,
            "feed_view": "people",
            **_listing_context(request, db, user, q, page,
                               author_ids=followed_user_ids(db, user.id)),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/feed/discussions")
def followed_discussions(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User = Depends(require_user), db: Session = Depends(get_db),
) -> Response:
    return render(request, "community/feed.html", {
        "title": "Discussions you follow", "user": user,
        "feed_view": "discussions", "page": "discussion-follows",
        **_listing_context(request, db, user, q, page, discussion_follower_id=user.id),
    }, headers={"Cache-Control": "no-store"})


@router.get("/topics")
def topics_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    topics = list_topics(db)
    return render(
        request,
        "community/topics.html",
        {"title": "Topics", "user": user, "topics": topics},
    )


@router.get("/topics/{slug}")
def topic_page(
    slug: str,
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    topic = get_topic_by_slug(db, slug)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return render(
        request,
        "community/topic.html",
        {
            "title": topic.name,
            "user": user,
            "topic": topic,
            "community_summary": growth.community_summaries(db, [topic], user)[topic.id],
            "can_manage_community": growth.can_manage_community(user, topic),
            "community_share_url": invitation_url(f"/topics/{topic.slug}"),
            **auth_context(db, f"/topics/{topic.slug}"),
            **share_preview(f"/topics/{topic.slug}", topic.name,
                            topic.description or "A public community for nurses at every stage."),
            **_listing_context(request, db, user, q, page, topic_id=topic.id),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/community/settings")
def community_settings(
    request: Request,
    user: User = Depends(require_user),
) -> Response:
    return render(
        request,
        "community/settings.html",
        {"title": "Community identity", "user": user, "name": user.community_name},
    )


@router.post("/community/settings")
def save_community_settings(
    request: Request,
    name: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    try:
        set_community_name(db, user, name)
    except CommunityError as exc:
        return render(
            request,
            "community/settings.html",
            {
                "title": "Community identity",
                "user": user,
                "name": name,
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return redirect_feedback(
        request, "/feed",
        message(
            'Community name saved',
            'This name will appear with your contributions.',
        ),
    )


@router.get("/posts/new")
def new_post_form(
    request: Request,
    topic: str = Query(""),
    kind: str = Query("question"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    context = _new_post_context(db)
    if any(str(item.id) == topic for item in context["topics"]):
        context["values"]["topic_id"] = topic
    context["values"]["post_kind"] = kind if kind in growth.POST_KINDS else "question"
    return render(
        request,
        "community/post_form.html",
        {"user": user, **context},
    )


@router.post("/posts")
def publish_post(
    request: Request,
    topic_id: str = Form(""),
    body: str = Form(""),
    community_name: str = Form(""),
    external_video_url: str = Form(""),
    draft_version: str = Form(""),
    post_kind: str = Form("discussion"),
    title: str = Form(""),
    activity_format: str = Form(""),
    activity_starts_at: str = Form(""),
    images: list[UploadFile] | None = File(None),
    video: UploadFile | None = File(None),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    values = {
        "topic_id": topic_id,
        "body": body,
        "external_video_url": external_video_url,
        "community_name": community_name,
        "post_kind": post_kind, "title": title, "activity_format": activity_format,
        "activity_starts_at": activity_starts_at,
    }
    retry_after = _retry_after(_post_limiter, user)
    if retry_after:
        return render(
            request,
            "community/post_form.html",
            {
                "user": user,
                **_new_post_context(
                    db,
                    values=values,
                    error="Too many posts. Try again after the retry period.",
                ),
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )
    try:
        parsed_topic_id = uuid.UUID(topic_id)
    except ValueError:
        error = "Choose an active topic."
    else:
        uploaded_images = [item for item in images or [] if item.filename]
        uploaded_video = video if video is not None and video.filename else None
        try:
            if not user.community_name and community_name.strip():
                set_community_name(db, user, community_name)
            post = create_post(
                db,
                user,
                topic_id=parsed_topic_id,
                body=body,
                post_kind=post_kind, title=title, activity_format=activity_format,
                activity_starts_at=activity_starts_at,
                external_video_url=external_video_url,
                images=[_stream_upload(item) for item in uploaded_images],
                video=(
                    _stream_upload(uploaded_video)
                    if uploaded_video is not None
                    else None
                ),
            )
        except CommunityError as exc:
            error = str(exc)
        else:
            confirm_published_draft(request, "post", draft_version)
            return redirect_feedback(
                request, f"/posts/{post.id}",
                message(
                    'Conversation published',
                    'Your conversation is now available to the community.',
                ),
            )

    return render(
        request,
        "community/post_form.html",
        {"user": user, **_new_post_context(db, values=values, error=error)},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.get("/posts/{post_id}")
def post_page(
    post_id: str,
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    reply_to: str | None = Query(None, max_length=36),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    context = _conversation_context(
        db, post, user, page_number=page, reply_to=reply_to or "",
        reply_target_explicit=reply_to is not None,
    )
    response = render(
        request,
        "community/post.html",
        context,
        headers={"Cache-Control": "no-store"},
    )
    if user is not None:
        mark_discussion_read(db, user, post, context["reply_page"].replies)
    return response


@router.get("/posts/{post_id}/unread")
def first_unread_page(
    post_id: str, user: User = Depends(require_user), db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=404)
    reply = first_unread_reply(db, user, post.id)
    destination = f"/posts/{post.id}#replies"
    if reply is not None:
        destination = f"/posts/{post.id}?page={reply_page_number(db, reply)}#reply-{reply.id}"
    return RedirectResponse(destination, status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/posts/{post_id}/replies/{reply_id}")
def reply_permalink(
    post_id: str, reply_id: str, db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=404)
    reply = db.scalar(select(CommunityReply).where(
        CommunityReply.id == _identifier(reply_id), CommunityReply.post_id == post.id,
        CommunityReply.status == ContentStatus.PUBLISHED,
    ))
    if reply is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(
        f"/posts/{post.id}?page={reply_page_number(db, reply)}#reply-{reply.id}",
        status_code=303, headers={"Cache-Control": "no-store"},
    )


@router.get("/posts/{post_id}/reply-context/{reply_id}")
def reply_context(post_id: str, reply_id: str, db: Session = Depends(get_db)) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=404)
    target_id = _identifier(reply_id)
    reference = reply_references(db, post.id, {target_id}).get(target_id)
    if reference is None:
        raise HTTPException(status_code=404)
    return JSONResponse(reference, headers={"Cache-Control": "no-store"})


@router.post("/posts/{post_id}/follow")
def subscribe_to_discussion(
    request: Request,
    post_id: str, user: User = Depends(require_user),
    _: None = Depends(verify_csrf), db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=404)
    follow_discussion(db, user, post)
    return redirect_feedback(
        request, f"/posts/{post.id}",
        message(
            'Discussion followed',
            'Find this conversation in Followed discussions.',
        ),
    )


@router.post("/posts/{post_id}/unfollow")
def unsubscribe_from_discussion(
    request: Request,
    post_id: str, user: User = Depends(require_user),
    _: None = Depends(verify_csrf), db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=404)
    unfollow_discussion(db, user, post)
    return redirect_feedback(
        request, f"/posts/{post.id}",
        message(
            'Discussion unfollowed',
            'This conversation has been removed from your followed discussions.',
        ),
    )


@router.post("/posts/{post_id}/replies")
def publish_reply(
    post_id: str,
    request: Request,
    body: str = Form(""),
    community_name: str = Form(""),
    draft_version: str = Form(""),
    in_reply_to_id: str = Form(""),
    page: int = Form(1, ge=1, le=10000),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    retry_after = _retry_after(_reply_limiter, user)
    if retry_after:
        return render(request, "community/post.html", _conversation_context(
            db, post, user, page_number=page, reply_body=body, reply_name=community_name,
            reply_to=in_reply_to_id, reply_target_explicit=True,
            reply_error="You have sent several replies. Please try again in a little while.",
        ), status_code=429, headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"})
    try:
        target_id = None
        if in_reply_to_id:
            try:
                target_id = uuid.UUID(in_reply_to_id)
            except ValueError:
                raise CommunityError(
                    "Choose an available response or reply to the conversation instead."
                ) from None
        if not user.community_name and community_name.strip():
            set_community_name(db, user, community_name)
        reply = add_reply(db, user, post, body, in_reply_to_id=target_id)
    except CommunityError as exc:
        return render(
            request,
            "community/post.html",
            _conversation_context(db, post, user, page_number=page, reply_error=str(exc),
                                  reply_body=body, reply_name=community_name,
                                  reply_to=in_reply_to_id, reply_target_explicit=True),
            status_code=status.HTTP_400_BAD_REQUEST,
            headers={"Cache-Control": "no-store"},
        )
    confirm_published_draft(request, f"reply:{post.id}", draft_version)
    return redirect_feedback(
        request, f"/posts/{post.id}?page={reply_page_number(db, reply)}#reply-{reply.id}",
        message(
            'Reply published',
            'Your reply has been added to the conversation.',
        ),
    )


@router.post("/posts/{post_id}/report")
def submit_post_report(
    request: Request,
    post_id: str,
    reason: str = Form(""),
    details: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    retry_after = _retry_after(_report_limiter, user)
    if retry_after:
        _raise_rate_limited(retry_after, "Too many reports. Try again later.")
    try:
        report_post(db, user, post, reason=reason, details=details)
    except CommunityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    return redirect_feedback(
        request, f"/posts/{post.id}",
        message(
            'Report received',
            'The moderation team can now review your report.',
        ),
    )


@router.post("/replies/{reply_id}/report")
def submit_reply_report(
    request: Request,
    reply_id: str,
    reason: str = Form(""),
    details: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    reply = db.get(CommunityReply, _identifier(reply_id))
    if reply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    retry_after = _retry_after(_report_limiter, user)
    if retry_after:
        _raise_rate_limited(retry_after, "Too many reports. Try again later.")
    try:
        report_reply(db, user, reply, reason=reason, details=details)
    except CommunityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    return redirect_feedback(
        request, f"/posts/{reply.post_id}",
        message(
            'Report received',
            'The moderation team can now review your report.',
        ),
    )


@router.get("/community/media/{media_id}", name="community_media")
def community_media(media_id: str, db: Session = Depends(get_db)) -> Response:
    media = get_public_media(db, _identifier(media_id))
    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        path = community_media_path(media.storage_name)
    except CommunityStorageError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(
        path,
        media_type=media.content_type,
        headers={
            "Cache-Control": "no-store" if db.get(Reel, media.post_id) else "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.get("/nurses")
def nurse_directory(
    request: Request,
    q: str = Query("", max_length=120),
    location: str = Query("", max_length=120),
    interest: str = Query("", max_length=60),
    professional_status: str = Query("", max_length=20),
    page: int = Query(1, ge=1, le=10000),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    filters = dict(
        query=q, location=location, interest=interest, professional_status=professional_status
    )
    total = count_discoverable_profiles(db, **filters)
    page_count = max(1, (total + 11) // 12)
    page = min(page, page_count)
    profiles = list_discoverable_profiles(db, limit=12, offset=(page - 1) * 12, **filters)
    cards = [
        {"profile": profile, "fields": public_profile_fields(db, profile)} for profile in profiles
    ]
    return render(
        request,
        "community/nurses.html",
        {
            "title": "Find people",
            "user": user,
            "cards": cards,
            "page": "nurses",
            "q": q,
            "location": location,
            "interest": interest,
            "professional_status": professional_status,
            "interest_options": INTEREST_OPTIONS,
            "status_options": PROFESSIONAL_STATUS_LABELS.items(),
            "total": total,
            "directory_page": page,
            "page_count": page_count,
            "has_filters": bool(q or location or interest or professional_status),
            "previous_url": "/nurses?"
            + urlencode(
                dict(
                    q=q,
                    location=location,
                    interest=interest,
                    professional_status=professional_status,
                    page=page - 1,
                )
            ),
            "next_url": "/nurses?"
            + urlencode(
                dict(
                    q=q,
                    location=location,
                    interest=interest,
                    professional_status=professional_status,
                    page=page + 1,
                )
            ),
        },
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@router.post("/nurses/{public_id}/follow")
def follow_nurse(
    request: Request,
    public_id: str,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = _public_profile(db, public_id)
    try:
        follow_profile(db, user, profile)
    except CommunityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return redirect_feedback(
        request, f"/p/{profile.public_id}",
        message(
            'Following',
            'Their community contributions can appear in your Following feed.',
        ),
    )


@router.post("/nurses/{public_id}/unfollow")
def unfollow_nurse(
    request: Request,
    public_id: str,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = _public_profile(db, public_id)
    unfollow_profile(db, user, profile)
    return redirect_feedback(
        request, f"/p/{profile.public_id}",
        message(
            'Unfollowed',
            'Their contributions will no longer be included because of this follow.',
        ),
    )


@router.post("/nurses/{public_id}/connect")
def connect_with_nurse(
    request: Request,
    public_id: str,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = _public_profile(db, public_id)
    try:
        request_connection(db, user, profile)
    except CommunityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return redirect_feedback(
        request, f"/p/{profile.public_id}",
        message(
            'Connection requested',
            'Your request is waiting for their response.',
        ),
    )


@router.get("/network")
def network_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    following_ids = followed_user_ids(db, user.id)
    received = list_received_requests(db, user.id)
    connections = list_connections(db, user.id)
    sent = list(
        db.scalars(
            select(Connection).where(
                Connection.requester_user_id == user.id,
                Connection.status == ConnectionStatus.PENDING,
            )
        ).all()
    )
    related_ids = set(following_ids)
    for item in [*received, *connections, *sent]:
        related_ids.update({item.requester_user_id, item.recipient_user_id})
    related_ids.discard(user.id)
    profiles = list(
        db.scalars(
            select(NurseProfile).where(
                NurseProfile.user_id.in_(related_ids) if related_ids else False,
                NurseProfile.status == ProfileStatus.ACTIVE,
                NurseProfile.discoverable.is_(True),
            )
        ).all()
    )
    return render(
        request,
        "community/network.html",
        {
            "title": "Your network",
            "user": user,
            "following": [p for p in profiles if p.user_id in following_ids],
            "received": received,
            "sent": sent,
            "connections": connections,
            "users": users_by_id(db, related_ids),
            "profile_ids": {p.user_id: p.public_id for p in profiles},
        },
    )


@router.post("/connections/{connection_id}/respond")
def answer_connection(
    request: Request,
    connection_id: str,
    action: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    connection = db.get(Connection, _identifier(connection_id))
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if action not in {"accept", "decline"}:
        raise HTTPException(status_code=400, detail="Choose accept or decline.")
    try:
        respond_to_connection(db, user, connection, accept=action == "accept")
    except CommunityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return redirect_feedback(
        request, "/network",
        message(
            'Connection request updated',
            'Your response has been saved.',
        ),
    )


@router.post("/connections/{connection_id}/remove")
def disconnect(
    request: Request,
    connection_id: str,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    connection = db.get(Connection, _identifier(connection_id))
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        remove_connection(db, user, connection)
    except CommunityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return redirect_feedback(
        request, "/network",
        message(
            'Connection removed',
            'You are no longer connected to this member.',
        ),
    )


def profile_social_context(
    db: Session,
    viewer: User | None,
    profile: NurseProfile,
) -> dict[str, object]:
    """Context shared with the existing public-profile route."""
    if viewer is None or viewer.id == profile.user_id or not profile.discoverable:
        return {"can_connect": False}
    connection = connection_between(db, viewer.id, profile.user_id)
    return {
        "can_connect": True,
        "is_following": follow_exists(db, viewer.id, profile.user_id),
        "connection": connection,
        "connection_status": connection.status if connection is not None else None,
    }
