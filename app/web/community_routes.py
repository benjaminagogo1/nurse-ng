"""Public community pages and authenticated participation actions."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.community_storage import CommunityStorageError, community_media_path
from app.core.config import settings
from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.community import CommunityReply, Connection, ConnectionStatus
from app.models.profile import NurseProfile, ProfileStatus
from app.models.user import User
from app.services.community import (
    REPORT_REASON_LABELS,
    CommunityError,
    CommunityUpload,
    add_reply,
    connection_between,
    create_post,
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
    public_profile_ids,
    remove_connection,
    report_post,
    report_reply,
    request_connection,
    respond_to_connection,
    set_community_name,
    unfollow_profile,
    users_by_id,
)
from app.services.profiles import (
    get_active_profile_by_public_id,
    list_discoverable_profiles,
    public_profile_fields,
)
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.templating import render

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
) -> dict[str, object]:
    author_ids = {post.author_id for post in posts}
    return {
        "posts": posts,
        "profile_ids": public_profile_ids(db, author_ids),
    }


def _new_post_context(
    db: Session,
    *,
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "title": "Start a discussion",
        "topics": list_topics(db),
        "values": values
        or {"topic_id": "", "body": "", "external_video_url": ""},
        "error": error,
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
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    posts = list_published_posts(db)
    return render(
        request,
        "community/feed.html",
        {
            "title": "Community feed",
            "user": user,
            "following_only": False,
            **_post_context(db, posts),
        },
    )


@router.get("/feed/following")
def following_feed(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    posts = list_published_posts(db, author_ids=followed_user_ids(db, user.id))
    return render(
        request,
        "community/feed.html",
        {
            "title": "Following feed",
            "user": user,
            "following_only": True,
            **_post_context(db, posts),
        },
    )


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
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    topic = get_topic_by_slug(db, slug)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    posts = list_published_posts(db, topic_id=topic.id)
    return render(
        request,
        "community/topic.html",
        {
            "title": topic.name,
            "user": user,
            "topic": topic,
            **_post_context(db, posts),
        },
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
    return RedirectResponse("/feed", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/posts/new")
def new_post_form(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    return render(
        request,
        "community/post_form.html",
        {"user": user, **_new_post_context(db)},
    )


@router.post("/posts")
def publish_post(
    request: Request,
    topic_id: str = Form(""),
    body: str = Form(""),
    external_video_url: str = Form(""),
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
            post = create_post(
                db,
                user,
                topic_id=parsed_topic_id,
                body=body,
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
            return RedirectResponse(
                f"/posts/{post.id}", status_code=status.HTTP_303_SEE_OTHER
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
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return render(
        request,
        "community/post.html",
        {
            "title": f"Discussion in {post.topic.name}",
            "user": user,
            "post": post,
            "profile_ids": public_profile_ids(
                db,
                {post.author_id, *(reply.author_id for reply in post.replies)},
            ),
            "report_reasons": REPORT_REASON_LABELS.items(),
        },
    )


@router.post("/posts/{post_id}/replies")
def publish_reply(
    post_id: str,
    request: Request,
    body: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    post = get_published_post(db, _identifier(post_id))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    retry_after = _retry_after(_reply_limiter, user)
    if retry_after:
        _raise_rate_limited(retry_after, "Too many replies. Try again later.")
    try:
        add_reply(db, user, post, body)
    except CommunityError as exc:
        return render(
            request,
            "community/post.html",
            {
                "title": f"Discussion in {post.topic.name}",
                "user": user,
                "post": post,
                "profile_ids": public_profile_ids(
                    db,
                    {post.author_id, *(reply.author_id for reply in post.replies)},
                ),
                "report_reasons": REPORT_REASON_LABELS.items(),
                "reply_error": str(exc),
                "reply_body": body,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(
        f"/posts/{post.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/posts/{post_id}/report")
def submit_post_report(
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
    return RedirectResponse(
        f"/posts/{post.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/replies/{reply_id}/report")
def submit_reply_report(
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
    return RedirectResponse(
        f"/posts/{reply.post_id}", status_code=status.HTTP_303_SEE_OTHER
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
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.get("/nurses")
def nurse_directory(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    profiles = list_discoverable_profiles(db)
    cards = [
        {"profile": profile, "fields": public_profile_fields(db, profile)}
        for profile in profiles
    ]
    return render(
        request,
        "community/nurses.html",
        {"title": "Find nurses", "user": user, "cards": cards},
    )


@router.post("/nurses/{public_id}/follow")
def follow_nurse(
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
    return RedirectResponse(
        f"/p/{profile.public_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/nurses/{public_id}/unfollow")
def unfollow_nurse(
    public_id: str,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = _public_profile(db, public_id)
    unfollow_profile(db, user, profile)
    return RedirectResponse(
        f"/p/{profile.public_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/nurses/{public_id}/connect")
def connect_with_nurse(
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
    return RedirectResponse(
        f"/p/{profile.public_id}", status_code=status.HTTP_303_SEE_OTHER
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
    return RedirectResponse("/network", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/connections/{connection_id}/remove")
def disconnect(
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
    return RedirectResponse("/network", status_code=status.HTTP_303_SEE_OTHER)


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
