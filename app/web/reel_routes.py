"""Dedicated Reels views, uploads and progressive enhancement endpoints."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.community import CommunityPost, ContentStatus, Follow
from app.models.reels import Reel, ReelSave
from app.models.user import User
from app.services.community import (
    REPORT_REASON_LABELS,
    CommunityError,
    CommunityUpload,
    add_reply,
    discussion_reply_page,
    discussion_summaries,
    followed_user_ids,
    list_topics,
    public_profile_ids,
    report_post,
    set_community_name,
)
from app.services.reels import (
    CATEGORIES,
    MAX_CAPTIONS_BYTES,
    PAGE_SIZE,
    create_reel,
    list_reels,
    public_reel,
    reel_query,
    remove_reel,
    retry_reel,
    save_reel,
    upload_by_key,
)
from app.web.community_routes import _post_limiter, _reply_limiter, _report_limiter, _retry_after
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/reels", tags=["reels"])


def _id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(404) from None


def _public(db: Session, post_id: str) -> Reel:
    reel = public_reel(db, _id(post_id))
    if reel is None:
        raise HTTPException(404)
    return reel


def _owned(db: Session, post_id: str, user: User) -> Reel:
    reel = db.scalar(reel_query().where(
        Reel.post_id == _id(post_id), CommunityPost.author_id == user.id,
        CommunityPost.status != ContentStatus.REMOVED,
    ))
    if reel is None:
        raise HTTPException(404)
    return reel


def _tiles(db: Session, reels: list[Reel], user: User | None) -> dict:
    posts = [reel.post for reel in reels]
    saved = set(db.scalars(select(ReelSave.post_id).where(
        ReelSave.user_id == user.id, ReelSave.post_id.in_([p.id for p in posts]),
    ))) if user else set()
    return {
        "tiles": [{"reel": reel, "media": {m.kind: m for m in reel.post.media}}
                  for reel in reels],
        "profile_ids": public_profile_ids(db, {p.author_id for p in posts}),
        "summaries": discussion_summaries(db, posts, user),
        "followed_ids": followed_user_ids(db, user.id) if user else set(),
        "saved_ids": saved, "categories": CATEGORIES, "report_reasons": REPORT_REASON_LABELS,
    }


@router.get("")
def index(
    request: Request, view: Literal["discover", "following", "saved"] = "discover",
    category: Literal["", "opportunities", "career", "learning", "stories"] = "",
    page: int = Query(1, ge=1, le=10000), user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if view != "discover" and user is None:
        return RedirectResponse("/auth/login", status_code=303)
    reels = list_reels(db, user=user, view=view, category=category, page=page)
    return render(request, "reels/feed.html", {
        "title": "Reels", "user": user, "view": view, "category": category,
        "page_number": page, "has_more": len(reels) > PAGE_SIZE, "single": False,
        **_tiles(db, reels[:PAGE_SIZE], user),
    })


@router.get("/new")
def upload_form(request: Request, user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    return _form(request, db, user, {"upload_key": str(uuid.uuid4())})


def _form(request, db, user, values, error="", status_code=200):
    return render(request, "reels/new.html", {
        "title": "Create a reel", "user": user, "values": values, "topics": list_topics(db),
        "categories": CATEGORIES, "max_bytes": settings.community_video_max_bytes,
        "max_seconds": settings.community_video_max_seconds,
        "feedback": message("Check your reel", error, tone="error") if error else None,
    }, status_code=status_code)


@router.post("")
def upload(
    request: Request, topic_id: str = Form(""), body: str = Form(""),
    category: str = Form("opportunities"), audience: str = Form("nigeria"),
    community_name: str = Form(""), upload_key: str = Form(""),
    cover_seconds: int = Form(0), job_link: str = Form(""), consent: str = Form(""),
    video: UploadFile | None = File(None), captions: UploadFile | None = File(None),
    user: User = Depends(require_user), _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    values = dict(topic_id=topic_id, body=body, category=category, audience=audience,
                  community_name=community_name, upload_key=upload_key,
                  cover_seconds=cover_seconds, job_link=job_link)
    wants_json = request.headers.get("x-reel-upload") == "1"
    existing = upload_by_key(db, user, upload_key)
    if existing:
        path = f"/reels/{existing.post_id}/status"
        return JSONResponse({"redirect": path}) if wants_json else RedirectResponse(path, 303)
    retry = _retry_after(_post_limiter, user)
    error, code = "", 400
    try:
        if retry:
            code = 429
            raise CommunityError("You have uploaded several posts. Please try again later.")
        if consent != "yes":
            raise CommunityError("Confirm that you want to publish this video publicly.")
        if video is None or not video.filename:
            raise CommunityError("Choose an MP4 video to upload.")
        try:
            topic = uuid.UUID(topic_id)
        except ValueError:
            raise CommunityError("Choose a community topic.") from None
        if not user.community_name:
            set_community_name(db, user, community_name)
        caption_data = captions.file.read(MAX_CAPTIONS_BYTES + 1) if captions else b""
        reel = create_reel(
            db, user, topic_id=topic, body=body, category=category, audience=audience,
            upload_key=upload_key, cover_seconds=cover_seconds, captions=caption_data,
            job_link=job_link, video=CommunityUpload(video.file, video.filename),
        )
    except CommunityError as exc:
        error = str(exc)
    else:
        path = f"/reels/{reel.post_id}/status"
        return JSONResponse({"redirect": path}, status_code=201) if wants_json else (
            RedirectResponse(path, status_code=303)
        )
    if wants_json:
        return JSONResponse({"error": error}, status_code=code,
                            headers={"Retry-After": str(retry)} if retry else {})
    return _form(request, db, user, values, error, code)


@router.get("/mine")
def mine(request: Request, page: int = Query(1, ge=1, le=10000),
         user: User = Depends(require_user), db: Session = Depends(get_db)):
    reels = list(db.scalars(reel_query().where(
        CommunityPost.author_id == user.id, CommunityPost.status != ContentStatus.REMOVED,
    ).order_by(Reel.created_at.desc()).offset((page - 1) * 20).limit(21)))
    return render(request, "reels/mine.html", {
        "title": "My reels", "user": user, "reels": reels[:20],
        "page_number": page, "has_more": len(reels) > 20,
    })


@router.get("/{post_id}/status")
def processing_status(post_id: str, request: Request, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    reel = _owned(db, post_id, user)
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"state": reel.state, "error": reel.error},
                            headers={"Cache-Control": "no-store"})
    return render(request, "reels/status.html", {"title": "Your reel", "user": user, "reel": reel})


@router.post("/{post_id}/retry")
def retry(post_id: str, request: Request, user: User = Depends(require_user),
          _: None = Depends(verify_csrf), db: Session = Depends(get_db)):
    reel = _owned(db, post_id, user)
    try:
        retry_reel(db, reel)
    except CommunityError as exc:
        return redirect_feedback(request, f"/reels/{post_id}/status",
                                 message("Cannot retry", str(exc), tone="error"))
    return RedirectResponse(f"/reels/{post_id}/status", status_code=303)


@router.post("/{post_id}/remove")
def remove(post_id: str, request: Request, user: User = Depends(require_user),
           _: None = Depends(verify_csrf), db: Session = Depends(get_db)):
    remove_reel(db, _owned(db, post_id, user), user)
    return redirect_feedback(request, "/reels/mine", message(
        "Reel removed", "Your video is no longer available to viewers.",
    ))


@router.get("/{post_id}/captions")
def subtitles(post_id: str, db: Session = Depends(get_db)):
    reel = _public(db, post_id)
    if not reel.captions:
        raise HTTPException(404)
    return Response(reel.captions, media_type="text/vtt", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'",
    })


def _action_response(request: Request, post_id: str, body: str, **data):
    if request.headers.get("x-reel-action") == "1":
        return JSONResponse({"message": body, **data}, headers={"Cache-Control": "no-store"})
    return redirect_feedback(request, f"/reels/{post_id}", message("Done", body))


@router.post("/{post_id}/save")
def save(post_id: str, request: Request, saved: Literal["yes", "no"] = Form(...),
         user: User = Depends(require_user), _: None = Depends(verify_csrf),
         db: Session = Depends(get_db)):
    save_reel(db, user, _public(db, post_id), saved=saved == "yes")
    return _action_response(request, post_id,
                            "Saved to your private collection." if saved == "yes" else
                            "Removed from your saved reels.", saved=saved == "yes")


@router.post("/{post_id}/follow")
def follow(post_id: str, request: Request, following: Literal["yes", "no"] = Form(...),
           user: User = Depends(require_user), _: None = Depends(verify_csrf),
           db: Session = Depends(get_db)):
    reel = _public(db, post_id)
    if reel.post.author_id == user.id:
        raise HTTPException(400, detail="You cannot follow yourself.")
    existing = db.scalar(select(Follow).where(
        Follow.follower_user_id == user.id, Follow.followed_user_id == reel.post.author_id,
    ))
    if following == "yes" and existing is None:
        db.add(Follow(follower_user_id=user.id, followed_user_id=reel.post.author_id))
    elif following == "no" and existing:
        db.delete(existing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if following != "yes":
            raise
    return _action_response(request, post_id,
                            "You are now following this creator." if following == "yes" else
                            "You have unfollowed this creator.", following=following == "yes")


@router.get("/{post_id}/comments")
def comments(post_id: str, request: Request, user: User | None = Depends(get_current_user),
             db: Session = Depends(get_db)):
    reel = _public(db, post_id)
    replies = discussion_reply_page(db, reel.post, user)
    return render(request, "reels/comments.html", {
        "reel": reel, "user": user, "reply_page": replies,
        "profile_ids": public_profile_ids(db, {r.author_id for r in replies.replies}),
    })


@router.post("/{post_id}/comments")
def comment(post_id: str, request: Request, body: str = Form(""), community_name: str = Form(""),
            user: User = Depends(require_user), _: None = Depends(verify_csrf),
            db: Session = Depends(get_db)):
    reel = _public(db, post_id)
    retry = _retry_after(_reply_limiter, user)
    if retry:
        return JSONResponse({"detail": "Please wait before sending another comment."}, 429,
                            headers={"Retry-After": str(retry)})
    try:
        if not user.community_name:
            set_community_name(db, user, community_name)
        add_reply(db, user, reel.post, body)
    except CommunityError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return _action_response(request, post_id, "Comment posted.")


@router.post("/{post_id}/report")
def report(post_id: str, request: Request, reason: str = Form(""), details: str = Form(""),
           user: User = Depends(require_user), _: None = Depends(verify_csrf),
           db: Session = Depends(get_db)):
    reel = _public(db, post_id)
    retry = _retry_after(_report_limiter, user)
    if retry:
        return JSONResponse({"detail": "Please wait before reporting again."}, 429,
                            headers={"Retry-After": str(retry)})
    try:
        report_post(db, user, reel.post, reason=reason, details=details)
    except CommunityError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return _action_response(request, post_id,
                            "Report received. Our moderation team will review it.")


@router.get("/{post_id}")
def detail(post_id: str, request: Request, user: User | None = Depends(get_current_user),
           db: Session = Depends(get_db)):
    reel = _public(db, post_id)
    return render(request, "reels/feed.html", {
        "title": "Reel by " + (reel.post.author.community_name or "Nurse.ng member"),
        "user": user, "view": "discover", "category": "", "page_number": 1,
        "has_more": False, "single": True, **_tiles(db, [reel], user),
    })
