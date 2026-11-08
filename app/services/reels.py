"""Publish, discover and save short videos without a second social graph."""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.community import CommunityPost, ContentStatus, Follow
from app.models.jobs import Job
from app.models.reels import Reel, ReelSave
from app.models.user import User
from app.services.community import (
    CommunityError,
    CommunityUpload,
    _remove_post_media,
    create_post,
)

CATEGORIES = {
    "opportunities": "Opportunities",
    "career": "Career",
    "learning": "Learning",
    "stories": "Our stories",
}
PAGE_SIZE = 8
MAX_CAPTIONS_BYTES = 64 * 1024
_TIMING = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> "
                     r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})$")


def clean_captions(data: bytes, maximum_seconds: int) -> str:
    """Accept plain WebVTT cues; no markup, CSS, regions, or remote resources."""
    if not data:
        return ""
    if len(data) > MAX_CAPTIONS_BYTES:
        raise CommunityError("Captions must be at most 64 KB.")
    try:
        value = data.decode("utf-8-sig").replace("\r\n", "\n").strip()
    except UnicodeDecodeError:
        raise CommunityError("Upload captions as a UTF-8 WebVTT (.vtt) file.") from None
    blocks = re.split(r"\n\s*\n", value)
    if not blocks or blocks[0] != "WEBVTT" or len(blocks) < 2:
        raise CommunityError("Captions need a WEBVTT header followed by timed cues.")
    result = ["WEBVTT"]
    for block in blocks[1:]:
        lines = block.splitlines()
        if lines and lines[0].isdigit():
            lines = lines[1:]
        match = _TIMING.fullmatch(lines[0]) if lines else None
        if not match or len(lines) < 2:
            raise CommunityError("Use caption times like 00:00:01.000 --> 00:00:04.000.")
        numbers = list(map(int, match.groups()))
        if any(numbers[i] >= 60 for i in (1, 2, 5, 6)):
            raise CommunityError("A caption contains an invalid time.")
        start = numbers[0] * 3600 + numbers[1] * 60 + numbers[2] + numbers[3] / 1000
        end = numbers[4] * 3600 + numbers[5] * 60 + numbers[6] + numbers[7] / 1000
        if not 0 <= start < end <= maximum_seconds:
            raise CommunityError("Caption times must fall within the video duration.")
        text = "\n".join(lines[1:])
        if any(ord(char) < 32 and char != "\n" for char in text) or "-->" in text:
            raise CommunityError("Captions contain unsupported characters.")
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        result.append(lines[0] + "\n" + text)
    return "\n\n".join(result) + "\n"


def upload_by_key(db: Session, user: User, key: str) -> Reel | None:
    return db.scalar(select(Reel).join(CommunityPost).where(
        Reel.upload_key == key, CommunityPost.author_id == user.id,
    ))


def create_reel(
    db: Session, user: User, *, topic_id: UUID, body: str, video: CommunityUpload,
    category: str, audience: str, upload_key: str, cover_seconds: int = 0,
    captions: bytes = b"", job_link: str = "",
) -> Reel:
    try:
        upload_key = str(UUID(upload_key))
    except ValueError:
        raise CommunityError("Reload the upload form and try again.") from None
    previous = upload_by_key(db, user, upload_key)
    if previous:
        return previous
    if category not in CATEGORIES or audience not in {"nigeria", "global"}:
        raise CommunityError("Choose a topic and audience for your reel.")
    if not body.strip() or len(body) > 2200:
        raise CommunityError("Add a caption of between 1 and 2,200 characters.")
    from app.core.config import settings

    if not 0 <= cover_seconds < settings.community_video_max_seconds:
        raise CommunityError("Choose a cover frame within your video.")
    job_id = None
    if job_link.strip():
        match = re.fullmatch(r"/jobs/([0-9a-fA-F-]{36})", job_link.strip())
        try:
            job_id = UUID(match[1]) if match else None
        except ValueError:
            job_id = None
        if job_id is None or db.get(Job, job_id) is None:
            raise CommunityError(
                "Use a Nurse.ng opportunity link, such as /jobs/ followed by its ID."
            )
    reel = Reel(
        upload_key=upload_key, category=category, audience=audience,
        job_id=job_id, cover_seconds=cover_seconds,
        captions=clean_captions(captions, settings.community_video_max_seconds),
    )
    try:
        create_post(db, user, topic_id=topic_id, body=body, external_video_url="",
                    video=video, reel=reel)
    except CommunityError:
        # A repeated upload request can race the original commit. The unique key
        # makes the original result authoritative without publishing twice.
        previous = upload_by_key(db, user, upload_key)
        if previous:
            return previous
        raise
    return reel


def reel_query():
    return select(Reel).join(CommunityPost).options(
        selectinload(Reel.post).selectinload(CommunityPost.author),
        selectinload(Reel.post).selectinload(CommunityPost.media),
        selectinload(Reel.post).selectinload(CommunityPost.topic),
    )


def public_reel(db: Session, post_id: UUID) -> Reel | None:
    return db.scalar(reel_query().where(
        Reel.post_id == post_id, Reel.state == "ready",
        CommunityPost.status == ContentStatus.PUBLISHED,
    ))


def list_reels(
    db: Session, *, user: User | None, view: str, category: str = "", page: int = 1,
) -> list[Reel]:
    query = reel_query().where(
        Reel.state == "ready", CommunityPost.status == ContentStatus.PUBLISHED,
    )
    if category:
        query = query.where(Reel.category == category)
    if view in {"following", "saved"}:
        if user is None:
            return []
        if view == "following":
            query = query.where(CommunityPost.author_id.in_(select(Follow.followed_user_id).where(
                Follow.follower_user_id == user.id,
            )))
        else:
            query = query.join(ReelSave).where(ReelSave.user_id == user.id)
    if view == "discover":
        query = query.order_by(case((Reel.audience == "nigeria", 0), else_=1))
    query = query.order_by(CommunityPost.published_at.desc(), Reel.post_id.desc())
    return list(db.scalars(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)))


def save_reel(db: Session, user: User, reel: Reel, *, saved: bool) -> None:
    if not saved:
        db.execute(delete(ReelSave).where(
            ReelSave.user_id == user.id, ReelSave.post_id == reel.post_id,
        ))
    elif db.get(ReelSave, (user.id, reel.post_id)) is None:
        db.add(ReelSave(user_id=user.id, post_id=reel.post_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not saved or db.get(ReelSave, (user.id, reel.post_id)) is None:
            raise


def retry_reel(db: Session, reel: Reel) -> None:
    changed = db.execute(update(Reel).where(
        Reel.post_id == reel.post_id, Reel.state == "failed", Reel.attempts < 3,
        Reel.post_id.in_(select(CommunityPost.id).where(
            CommunityPost.status == ContentStatus.PROCESSING,
        )),
    ).values(state="queued", error="", lease_token=None, lease_until=None))
    if not changed.rowcount:
        db.rollback()
        raise CommunityError(
            "This reel cannot be retried. Upload a new video if processing failed."
        )
    db.commit()


def remove_reel(db: Session, reel: Reel, user: User) -> None:
    if reel.post.author_id != user.id:
        raise CommunityError("Only the creator can remove this reel.")
    reel.post.status = ContentStatus.REMOVED
    reel.post.removed_at = datetime.now(UTC)
    reel.post.removed_by_user_id = user.id
    reel.post.removal_reason = "Removed by creator."
    # Revoke a worker's lease before releasing files.
    reel.lease_token = None
    reel.lease_until = None
    db.commit()
    _remove_post_media(db, reel.post)
