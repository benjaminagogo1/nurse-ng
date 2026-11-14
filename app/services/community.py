"""Community publishing, moderation, and member-relationship rules."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from logging import getLogger
from typing import TYPE_CHECKING, BinaryIO
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.community_storage import (
    CommunityStorageError,
    cleanup_orphan_community_media,
    delete_community_media,
    save_community_media,
)
from app.core.config import settings
from app.models.community import (
    CommunityMedia,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    ConnectionStatus,
    ContentReport,
    ContentStatus,
    DiscussionFollow,
    DiscussionReplyRead,
    Follow,
    MediaKind,
    ReportReason,
    ReportStatus,
)
from app.models.profile import NurseProfile, ProfileStatus
from app.models.user import User
from app.services.notifications import notify_connection, notify_reply

if TYPE_CHECKING:
    from app.models.reels import Reel

COMMUNITY_NAME_MAX = 80
POST_BODY_MAX = 5000
REPLY_BODY_MAX = 2000
REPLIES_PER_PAGE = 20
TOPIC_NAME_MAX = 80
TOPIC_DESCRIPTION_MAX = 500
REPORT_DETAILS_MAX = 1000
MODERATION_NOTE_MAX = 1000
EXTERNAL_URL_MAX = 2048
MAX_IMAGES_PER_POST = 4
logger = getLogger(__name__)

_RESERVED_COMMUNITY_NAME_KEYS = frozenset(
    {
        "admin",
        "administrator",
        "help",
        "moderator",
        "nmcn",
        "nurseng",
        "nursingandmidwiferycouncilofnigeria",
        "official",
        "staff",
        "support",
    }
)

REPORT_REASON_LABELS: dict[str, str] = {
    ReportReason.SPAM.value: "Spam",
    ReportReason.HARASSMENT.value: "Harassment or bullying",
    ReportReason.MISINFORMATION.value: "Potentially harmful misinformation",
    ReportReason.PRIVACY.value: "Privacy concern",
    ReportReason.OTHER.value: "Other",
}


class CommunityError(ValueError):
    """Community input or action the requester can correct."""


@dataclass(frozen=True)
class CommunityUpload:
    file: BinaryIO
    filename: str


def _clean_text(
    value: str,
    *,
    field: str,
    maximum: int,
    required: bool = False,
) -> str:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise CommunityError(f"{field} is required.")
    if len(cleaned) > maximum:
        raise CommunityError(f"{field} must be at most {maximum} characters.")
    if any(ord(character) < 32 and character not in "\n\t" for character in cleaned):
        raise CommunityError(f"{field} contains unsupported control characters.")
    return cleaned


def _clean_community_name(name: str) -> tuple[str, str]:
    normalised = unicodedata.normalize("NFKC", name or "")
    cleaned = " ".join(normalised.split())
    if not cleaned:
        raise CommunityError("Community name is required.")
    if len(cleaned) > COMMUNITY_NAME_MAX:
        raise CommunityError(
            f"Community name must be at most {COMMUNITY_NAME_MAX} characters."
        )
    if len(cleaned) < 2:
        raise CommunityError("Community name must be at least 2 characters.")
    if any(unicodedata.category(character).startswith("C") for character in cleaned):
        raise CommunityError("Community name contains unsupported characters.")
    key = cleaned.casefold()
    key = " ".join(key.split())
    reserved_key = "".join(character for character in key if character.isalnum())
    if reserved_key in _RESERVED_COMMUNITY_NAME_KEYS:
        raise CommunityError("Choose a name that does not imply official or staff status.")
    return cleaned, key


def set_community_name(db: Session, user: User, name: str) -> User:
    """Set a unique public name before the member's first contribution."""
    cleaned, key = _clean_community_name(name)
    if user.community_name_locked:
        if user.community_name == cleaned:
            return user
        raise CommunityError(
            "Your community name is locked because you have already contributed."
        )
    try:
        result = db.execute(
            update(User)
            .where(User.id == user.id, User.community_name_locked.is_(False))
            .values(community_name=cleaned, community_name_key=key)
        )
        if result.rowcount != 1:
            db.rollback()
            raise CommunityError(
                "Your community name is locked because you have already contributed."
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CommunityError("That community name is already in use.") from None
    db.refresh(user)
    return user


def _require_community_name(user: User) -> None:
    if not (user.community_name or "").strip():
        raise CommunityError(
            "Choose a public community name before posting or replying."
        )


def _lock_community_name(db: Session, user: User) -> None:
    _require_community_name(user)
    if user.community_name_locked:
        return
    result = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.community_name_locked.is_(False),
            User.community_name_key.is_not(None),
        )
        .values(community_name_locked=True)
    )
    if result.rowcount != 1:
        raise CommunityError("Choose a public community name before contributing.")
    user.community_name_locked = True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _reserve_upload_quota(db: Session, user: User, size_bytes: int) -> None:
    if size_bytes <= 0:
        return
    account = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if account is None:
        raise CommunityError("The account could not be found.")
    now = datetime.now(UTC)
    window_started = account.community_upload_window_started_at
    if (
        window_started is None
        or _as_utc(window_started)
        + timedelta(seconds=settings.community_upload_window_seconds)
        <= now
    ):
        account.community_upload_window_started_at = now
        account.community_upload_window_bytes = 0

    if (
        account.community_upload_window_bytes + size_bytes
        > settings.community_upload_window_bytes
    ):
        raise CommunityError("Your 24-hour community upload allowance is exhausted.")
    if account.community_storage_bytes + size_bytes > settings.community_storage_quota_bytes:
        raise CommunityError("Your community media storage allowance is exhausted.")

    account.community_upload_window_bytes += size_bytes
    account.community_storage_bytes += size_bytes


def _topic_slug(name: str) -> str:
    normalised = unicodedata.normalize("NFKD", name)
    ascii_name = normalised.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    if not slug:
        raise CommunityError("Topic name must contain a letter or number.")
    return slug[:80].rstrip("-")


def create_topic(
    db: Session,
    staff: User,
    *,
    name: str,
    description: str,
) -> CommunityTopic:
    """Create a topic. Topic creation is an explicit staff operation."""
    if not staff.is_staff:
        raise CommunityError("Staff access is required to create a topic.")
    clean_name = _clean_text(
        name,
        field="Topic name",
        maximum=TOPIC_NAME_MAX,
        required=True,
    )
    clean_description = _clean_text(
        description,
        field="Topic description",
        maximum=TOPIC_DESCRIPTION_MAX,
    )
    topic = CommunityTopic(
        name=clean_name,
        slug=_topic_slug(clean_name),
        description=clean_description,
        created_by_user_id=staff.id,
        is_active=True,
    )
    db.add(topic)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CommunityError("A topic with that name already exists.") from None
    db.refresh(topic)
    return topic


def list_topics(db: Session, *, active_only: bool = True) -> list[CommunityTopic]:
    statement = select(CommunityTopic)
    if active_only:
        statement = statement.where(CommunityTopic.is_active.is_(True))
    return list(db.scalars(statement.order_by(CommunityTopic.name)).all())


def get_topic_by_slug(db: Session, slug: str) -> CommunityTopic | None:
    return db.scalar(
        select(CommunityTopic).where(
            CommunityTopic.slug == slug,
            CommunityTopic.is_active.is_(True),
        )
    )


def _external_video_url(value: str) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > EXTERNAL_URL_MAX:
        raise CommunityError("External video URL is too long.")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CommunityError("Enter a complete http:// or https:// video URL.")
    if parsed.username or parsed.password:
        raise CommunityError("External video URLs cannot include login details.")
    return cleaned


def create_post(
    db: Session,
    user: User,
    *,
    topic_id: UUID,
    body: str,
    external_video_url: str,
    images: Sequence[CommunityUpload] = (),
    video: CommunityUpload | None = None,
    reel: "Reel | None" = None,
) -> CommunityPost:
    """Run synchronous checks, store media, and publish one topic post."""
    _require_community_name(user)
    if reel is not None and (video is None or images or external_video_url):
        raise CommunityError("A reel needs one uploaded video.")
    topic = db.get(CommunityTopic, topic_id)
    if topic is None or not topic.is_active:
        raise CommunityError("Choose an active topic.")
    if len(images) > MAX_IMAGES_PER_POST:
        raise CommunityError(
            f"A post can contain at most {MAX_IMAGES_PER_POST} images."
        )

    clean_body = _clean_text(body, field="Post", maximum=POST_BODY_MAX)
    clean_url = _external_video_url(external_video_url)
    if not clean_body and not images and video is None and clean_url is None:
        raise CommunityError("Add text, media, or an external video link.")

    post = CommunityPost(
        author_id=user.id,
        topic_id=topic.id,
        body=clean_body,
        external_video_url=clean_url,
        status=ContentStatus.PROCESSING if reel is not None else ContentStatus.PUBLISHED,
    )
    db.add(post)
    stored_names: list[str] = []
    stored_size = 0
    uploads: list[tuple[str, CommunityUpload]] = [
        (MediaKind.IMAGE.value, upload) for upload in images
    ]
    if video is not None:
        uploads.append((MediaKind.VIDEO.value, video))

    try:
        _lock_community_name(db, user)
        for position, (kind, upload) in enumerate(uploads):
            storage_name, content_type, size_bytes, duration = save_community_media(
                upload.file, kind
            )
            stored_names.append(storage_name)
            if reel is not None:
                from app.services.reels import clean_captions

                if reel.cover_seconds >= duration:
                    raise CommunityError("Choose a cover frame within your video.")
                if reel.captions:
                    clean_captions(reel.captions.encode(), duration)
            stored_size += size_bytes
            post.media.append(
                CommunityMedia(
                    kind=MediaKind.REEL_SOURCE if reel is not None else kind,
                    original_filename=(upload.filename or "")[:255],
                    storage_name=storage_name,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    duration_seconds=duration,
                    position=position,
                )
            )
        _reserve_upload_quota(db, user, stored_size)
        if reel is not None:
            reel.post = post
            db.add(reel)
        db.commit()
    except (CommunityStorageError, CommunityError, SQLAlchemyError) as exc:
        db.rollback()
        for storage_name in stored_names:
            delete_community_media(storage_name)
        if isinstance(exc, (CommunityStorageError, CommunityError)):
            raise CommunityError(str(exc)) from None
        raise CommunityError("The post could not be published.") from None

    db.refresh(post)
    return post


def _post_load_options(*, replies: bool = True):
    options = (
        selectinload(CommunityPost.author),
        selectinload(CommunityPost.topic),
        selectinload(CommunityPost.media),
    )
    if replies:
        options += (selectinload(CommunityPost.replies).selectinload(CommunityReply.author),)
    return options


def list_published_posts(
    db: Session,
    *,
    topic_id: UUID | None = None,
    author_ids: set[UUID] | None = None,
    limit: int = 50,
    offset: int = 0,
    query: str = "",
    discussion_follower_id: UUID | None = None,
) -> list[CommunityPost]:
    statement = select(CommunityPost).where(
        CommunityPost.status == ContentStatus.PUBLISHED
    )
    if topic_id is not None:
        statement = statement.where(CommunityPost.topic_id == topic_id)
    if author_ids is not None:
        if not author_ids:
            return []
        statement = statement.where(CommunityPost.author_id.in_(author_ids))
    for word in query.strip().split():
        matching_reply = select(CommunityReply.id).where(
            CommunityReply.post_id == CommunityPost.id,
            CommunityReply.status == ContentStatus.PUBLISHED,
            CommunityReply.body.icontains(word, autoescape=True),
        ).exists()
        statement = statement.where(or_(
            CommunityPost.body.icontains(word, autoescape=True),
            CommunityPost.topic.has(CommunityTopic.name.icontains(word, autoescape=True)),
            matching_reply,
        ))
    order = CommunityPost.published_at
    if discussion_follower_id is not None:
        statement = statement.join(DiscussionFollow).where(
            DiscussionFollow.user_id == discussion_follower_id
        )
        latest_reply = select(func.max(CommunityReply.created_at)).where(
            CommunityReply.post_id == CommunityPost.id,
            CommunityReply.status == ContentStatus.PUBLISHED,
        ).correlate(CommunityPost).scalar_subquery()
        order = func.coalesce(latest_reply, CommunityPost.published_at)
    statement = statement.options(*_post_load_options(replies=False)).order_by(
        order.desc(), CommunityPost.id.desc()
    )
    return list(db.scalars(statement.offset(offset).limit(limit)).all())


def discussion_summaries(
    db: Session, posts: Sequence[CommunityPost], user: User | None = None,
) -> dict[UUID, dict[str, object]]:
    """Batch visible reply counts and this member's private update indicators."""
    result = {
        post.id: {"replies": 0, "last_reply_at": None, "following": False, "new_replies": 0}
        for post in posts
    }
    if not result:
        return result
    from app.services.engagement import like_summaries

    for post_id, likes in like_summaries(db, result, user).items():
        result[post_id].update(likes)
    for post_id, count, latest in db.execute(
        select(CommunityReply.post_id, func.count(), func.max(CommunityReply.created_at))
        .where(CommunityReply.post_id.in_(result), CommunityReply.status == ContentStatus.PUBLISHED)
        .group_by(CommunityReply.post_id)
    ):
        result[post_id].update(replies=count, last_reply_at=latest)
    if user is not None:
        for post_id in db.scalars(select(DiscussionFollow.post_id).where(
            DiscussionFollow.user_id == user.id, DiscussionFollow.post_id.in_(result),
        )):
            result[post_id]["following"] = True
        for post_id, count in db.execute(
            select(CommunityReply.post_id, func.count())
            .join(DiscussionFollow, DiscussionFollow.post_id == CommunityReply.post_id)
            .where(
                DiscussionFollow.user_id == user.id, CommunityReply.post_id.in_(result),
                CommunityReply.status == ContentStatus.PUBLISHED,
                CommunityReply.author_id != user.id,
                CommunityReply.created_at > DiscussionFollow.last_read_at,
                ~_reply_read_exists(),
            ).group_by(CommunityReply.post_id)
        ):
            result[post_id]["new_replies"] = count
    return result


def follow_discussion(db: Session, user: User, post: CommunityPost) -> None:
    if post.status != ContentStatus.PUBLISHED:
        raise CommunityError("This conversation is no longer available.")
    existing = db.scalar(select(DiscussionFollow.id).where(
        DiscussionFollow.user_id == user.id, DiscussionFollow.post_id == post.id,
    ))
    if existing is not None:
        return
    db.add(DiscussionFollow(user_id=user.id, post_id=post.id, last_read_at=datetime.now(UTC)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(DiscussionFollow.id).where(
            DiscussionFollow.user_id == user.id, DiscussionFollow.post_id == post.id,
        )) is None:
            raise


def unfollow_discussion(db: Session, user: User, post: CommunityPost) -> None:
    db.execute(delete(DiscussionFollow).where(
        DiscussionFollow.user_id == user.id, DiscussionFollow.post_id == post.id,
    ))
    db.commit()


def _reply_read_exists():
    return select(DiscussionReplyRead.reply_id).where(
        DiscussionReplyRead.follow_id == DiscussionFollow.id,
        DiscussionReplyRead.reply_id == CommunityReply.id,
    ).correlate(DiscussionFollow, CommunityReply).exists()


def _unread_replies(user: User, post_id: UUID):
    return select(CommunityReply).join(
        DiscussionFollow, DiscussionFollow.post_id == CommunityReply.post_id,
    ).where(
        DiscussionFollow.user_id == user.id,
        CommunityReply.post_id == post_id,
        CommunityReply.status == ContentStatus.PUBLISHED,
        CommunityReply.author_id != user.id,
        CommunityReply.created_at > DiscussionFollow.last_read_at,
        ~_reply_read_exists(),
    )


def first_unread_reply(db: Session, user: User, post_id: UUID) -> CommunityReply | None:
    return db.scalar(_unread_replies(user, post_id).order_by(
        CommunityReply.created_at, CommunityReply.id,
    ).limit(1))


@dataclass(frozen=True)
class ReplyPage:
    replies: Sequence[CommunityReply]
    number: int
    total_pages: int
    total_replies: int
    unread_ids: frozenset[UUID]
    first_unread_id: UUID | None


def discussion_reply_page(
    db: Session, post: CommunityPost, user: User | None = None, *, page: int = 1,
) -> ReplyPage:
    visible = select(CommunityReply).where(
        CommunityReply.post_id == post.id, CommunityReply.status == ContentStatus.PUBLISHED,
    )
    total = db.scalar(visible.with_only_columns(func.count()).select_from(CommunityReply)) or 0
    total_pages = max(1, (total + REPLIES_PER_PAGE - 1) // REPLIES_PER_PAGE)
    page = min(max(1, page), total_pages)
    replies = list(db.scalars(visible.order_by(
        CommunityReply.created_at, CommunityReply.id,
    ).offset((page - 1) * REPLIES_PER_PAGE).limit(REPLIES_PER_PAGE).options(
        selectinload(CommunityReply.author),
    )))
    unread_ids = frozenset()
    first_unread = None
    if user is not None:
        first_unread = first_unread_reply(db, user, post.id)
        if first_unread is not None and replies:
            unread_ids = frozenset(db.scalars(_unread_replies(user, post.id).where(
                CommunityReply.id.in_([reply.id for reply in replies]),
            ).with_only_columns(CommunityReply.id)))
    return ReplyPage(replies, page, total_pages, total, unread_ids,
                     first_unread.id if first_unread else None)


def reply_page_number(db: Session, reply: CommunityReply) -> int:
    earlier = db.scalar(select(func.count()).select_from(CommunityReply).where(
        CommunityReply.post_id == reply.post_id,
        CommunityReply.status == ContentStatus.PUBLISHED,
        or_(CommunityReply.created_at < reply.created_at,
            (CommunityReply.created_at == reply.created_at) & (CommunityReply.id < reply.id)),
    )) or 0
    return earlier // REPLIES_PER_PAGE + 1


def reply_references(db: Session, post_id: UUID, reply_ids: set[UUID]) -> dict[UUID, dict]:
    """Resolve only immediate public references, never copy removed text or load a tree."""
    if not reply_ids:
        return {}
    rows = db.execute(select(CommunityReply.id, User.community_name, CommunityReply.body).join(
        User, User.id == CommunityReply.author_id,
    ).where(
        CommunityReply.post_id == post_id, CommunityReply.id.in_(reply_ids),
        CommunityReply.status == ContentStatus.PUBLISHED,
    ).limit(len(reply_ids)))
    result = {}
    for reply_id, name, body in rows:
        excerpt = " ".join(body.split())
        result[reply_id] = {
            "id": str(reply_id), "author": name or "Nurse.ng member",
            "excerpt": excerpt[:180] + ("…" if len(excerpt) > 180 else ""),
            "url": f"/posts/{post_id}/replies/{reply_id}",
        }
    return result


def mark_discussion_read(
    db: Session, user: User, post: CommunityPost, replies: Sequence[CommunityReply],
) -> None:
    # Record only rendered replies, leaving gaps and concurrently arriving replies new.
    if not replies:
        return
    rows = _unread_replies(user, post.id).where(
        CommunityReply.id.in_([reply.id for reply in replies]),
    ).with_only_columns(DiscussionFollow.id, CommunityReply.id)
    # Both supported databases offer an atomic insert that tolerates overlapping reads.
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgresql_insert
    db.execute(insert(DiscussionReplyRead).from_select(
        ["follow_id", "reply_id"], rows,
    ).on_conflict_do_nothing(index_elements=["follow_id", "reply_id"]))
    db.commit()


def get_published_post(db: Session, post_id: UUID) -> CommunityPost | None:
    return db.scalar(
        select(CommunityPost)
        .where(
            CommunityPost.id == post_id,
            CommunityPost.status == ContentStatus.PUBLISHED,
        )
        .options(*_post_load_options(replies=False))
        .execution_options(populate_existing=True)
    )


def add_reply(
    db: Session,
    user: User,
    post: CommunityPost,
    body: str,
    *,
    in_reply_to_id: UUID | None = None,
) -> CommunityReply:
    _require_community_name(user)
    if post.status != ContentStatus.PUBLISHED:
        raise CommunityError("This conversation is no longer open.")
    cleaned = _clean_text(
        body,
        field="Reply",
        maximum=REPLY_BODY_MAX,
        required=True,
    )
    if in_reply_to_id is not None and db.scalar(select(CommunityReply.id).where(
        CommunityReply.id == in_reply_to_id, CommunityReply.post_id == post.id,
        CommunityReply.status == ContentStatus.PUBLISHED,
    )) is None:
        raise CommunityError(
            "The response you selected is no longer available. "
            "Choose another response or reply to the conversation instead."
        )
    reply = CommunityReply(
        post_id=post.id,
        author_id=user.id,
        body=cleaned,
        in_reply_to_id=in_reply_to_id,
        status=ContentStatus.PUBLISHED,
        created_at=datetime.now(UTC),
    )
    _lock_community_name(db, user)
    db.add(reply)
    db.flush()
    notify_reply(db, reply, post)
    db.commit()
    db.refresh(reply)
    return reply


def _clean_report(reason: str, details: str) -> tuple[str, str]:
    clean_reason = (reason or "").strip()
    if clean_reason not in REPORT_REASON_LABELS:
        raise CommunityError("Choose a valid report reason.")
    clean_details = _clean_text(
        details,
        field="Report details",
        maximum=REPORT_DETAILS_MAX,
    )
    if clean_reason == ReportReason.OTHER.value and not clean_details:
        raise CommunityError("Describe the concern when choosing Other.")
    return clean_reason, clean_details


def report_post(
    db: Session,
    user: User,
    post: CommunityPost,
    *,
    reason: str,
    details: str,
) -> ContentReport:
    if post.status != ContentStatus.PUBLISHED:
        raise CommunityError("This post is no longer public.")
    if post.author_id == user.id:
        raise CommunityError("You cannot report your own post.")
    clean_reason, clean_details = _clean_report(reason, details)
    report = ContentReport(
        reporter_id=user.id,
        post_id=post.id,
        reason=clean_reason,
        details=clean_details,
        status=ReportStatus.OPEN,
        open_key=f"post:{user.id.hex}:{post.id.hex}",
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CommunityError("You already reported this post.") from None
    db.refresh(report)
    return report


def report_reply(
    db: Session,
    user: User,
    reply: CommunityReply,
    *,
    reason: str,
    details: str,
) -> ContentReport:
    if reply.status != ContentStatus.PUBLISHED:
        raise CommunityError("This reply is no longer public.")
    if reply.post.status != ContentStatus.PUBLISHED:
        raise CommunityError("This conversation is no longer public.")
    if reply.author_id == user.id:
        raise CommunityError("You cannot report your own reply.")
    clean_reason, clean_details = _clean_report(reason, details)
    report = ContentReport(
        reporter_id=user.id,
        reply_id=reply.id,
        reason=clean_reason,
        details=clean_details,
        status=ReportStatus.OPEN,
        open_key=f"reply:{user.id.hex}:{reply.id.hex}",
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CommunityError("You already reported this reply.") from None
    db.refresh(report)
    return report


def list_open_reports(db: Session) -> list[ContentReport]:
    return list(
        db.scalars(
            select(ContentReport)
            .where(ContentReport.status == ReportStatus.OPEN)
            .options(
                selectinload(ContentReport.post).selectinload(CommunityPost.author),
                selectinload(ContentReport.reply).selectinload(CommunityReply.author),
            )
            .order_by(ContentReport.created_at)
        ).all()
    )


def moderate_report(
    db: Session,
    staff: User,
    report: ContentReport,
    *,
    action: str,
    note: str,
) -> ContentReport:
    """Dismiss a report or remove its target, retaining an audit row."""
    if not staff.is_staff:
        raise CommunityError("Staff access is required.")
    if action not in {"remove", "dismiss"}:
        raise CommunityError("Choose remove or dismiss.")
    clean_note = _clean_text(
        note,
        field="Moderation note",
        maximum=MODERATION_NOTE_MAX,
        required=True,
    )
    now = datetime.now(UTC)
    target = report.post or report.reply
    if action == "remove" and target is None:
        raise CommunityError("The reported content no longer exists.")

    report_status = (
        ReportStatus.RESOLVED if action == "remove" else ReportStatus.DISMISSED
    )
    claimed = db.execute(
        update(ContentReport)
        .where(
            ContentReport.id == report.id,
            ContentReport.status == ReportStatus.OPEN,
        )
        .values(
            status=report_status,
            reviewed_by_user_id=staff.id,
            reviewed_at=now,
            review_note=clean_note,
            open_key=None,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise CommunityError("This report has already been reviewed.")

    removed_post: CommunityPost | None = None
    if action == "remove" and target is not None:
        target_model = CommunityPost if report.post_id is not None else CommunityReply
        removed = db.execute(
            update(target_model)
            .where(
                target_model.id == target.id,
                target_model.status == ContentStatus.PUBLISHED,
            )
            .values(
                status=ContentStatus.REMOVED,
                removed_by_user_id=staff.id,
                removed_at=now,
                removal_reason=clean_note,
            )
        )
        if removed.rowcount != 1:
            db.rollback()
            raise CommunityError("The reported content is no longer public.")
        target_filter = (
            ContentReport.post_id == report.post_id
            if report.post_id is not None
            else ContentReport.reply_id == report.reply_id
        )
        db.execute(
            update(ContentReport)
            .where(
                target_filter,
                ContentReport.status == ReportStatus.OPEN,
                ContentReport.id != report.id,
            )
            .values(
                status=ReportStatus.RESOLVED,
                reviewed_by_user_id=staff.id,
                reviewed_at=now,
                review_note="Closed because the content was removed.",
                open_key=None,
            )
        )
        if isinstance(target, CommunityPost):
            removed_post = target
    db.commit()
    db.refresh(report)
    if removed_post is not None:
        _remove_post_media(db, removed_post)
    return report


def _remove_post_media(db: Session, post: CommunityPost) -> None:
    media = list(post.media)
    if not media:
        return
    storage_names = [item.storage_name for item in media]
    released_bytes = sum(item.size_bytes for item in media)
    account = db.scalar(select(User).where(User.id == post.author_id).with_for_update())
    if account is not None:
        account.community_storage_bytes = max(
            0, account.community_storage_bytes - released_bytes
        )
    for item in media:
        db.delete(item)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not release media records for removed post %s", post.id)
        return
    for storage_name in storage_names:
        delete_community_media(storage_name)


def get_public_media(db: Session, media_id: UUID) -> CommunityMedia | None:
    return db.scalar(
        select(CommunityMedia)
        .join(CommunityPost, CommunityMedia.post_id == CommunityPost.id)
        .where(
            CommunityMedia.id == media_id,
            CommunityMedia.kind != MediaKind.REEL_SOURCE,
            CommunityPost.status == ContentStatus.PUBLISHED,
        )
    )


def follow_profile(
    db: Session,
    user: User,
    profile: NurseProfile,
) -> Follow:
    if profile.user_id == user.id:
        raise CommunityError("You cannot follow yourself.")
    if profile.status != ProfileStatus.ACTIVE or not profile.discoverable:
        raise CommunityError("This profile is not public.")
    existing = db.scalar(
        select(Follow).where(
            Follow.follower_user_id == user.id,
            Follow.followed_user_id == profile.user_id,
        )
    )
    if existing is not None:
        return existing
    item = Follow(follower_user_id=user.id, followed_user_id=profile.user_id)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Follow).where(
                Follow.follower_user_id == user.id,
                Follow.followed_user_id == profile.user_id,
            )
        )
        if existing is None:
            raise CommunityError("The profile could not be followed.") from None
        return existing
    db.refresh(item)
    return item


def unfollow_profile(db: Session, user: User, profile: NurseProfile) -> None:
    item = db.scalar(
        select(Follow).where(
            Follow.follower_user_id == user.id,
            Follow.followed_user_id == profile.user_id,
        )
    )
    if item is not None:
        db.delete(item)
        db.commit()


def request_connection(
    db: Session,
    user: User,
    profile: NurseProfile,
) -> Connection:
    if profile.user_id == user.id:
        raise CommunityError("You cannot connect with yourself.")
    if profile.status != ProfileStatus.ACTIVE or not profile.discoverable:
        raise CommunityError("This profile is not public.")
    pair_key = connection_pair_key(user.id, profile.user_id)
    existing = db.scalar(select(Connection).where(Connection.pair_key == pair_key))
    if existing is not None:
        if existing.status == ConnectionStatus.DECLINED:
            existing.requester_user_id = user.id
            existing.recipient_user_id = profile.user_id
            existing.status = ConnectionStatus.PENDING
            existing.responded_at = None
            db.flush()
            notify_connection(db, existing)
            db.commit()
            db.refresh(existing)
        return existing
    item = Connection(
        requester_user_id=user.id,
        recipient_user_id=profile.user_id,
        status=ConnectionStatus.PENDING,
        pair_key=pair_key,
    )
    db.add(item)
    try:
        db.flush()
        notify_connection(db, item)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Connection).where(Connection.pair_key == pair_key))
        if existing is None:
            raise CommunityError("The connection request could not be saved.") from None
        return existing
    db.refresh(item)
    return item


def connection_between(
    db: Session,
    first_user_id: UUID,
    second_user_id: UUID,
) -> Connection | None:
    return db.scalar(
        select(Connection).where(
            Connection.pair_key == connection_pair_key(first_user_id, second_user_id)
        )
    )


def connection_pair_key(first_user_id: UUID, second_user_id: UUID) -> str:
    first, second = sorted((first_user_id.hex, second_user_id.hex))
    return f"{first}:{second}"


def respond_to_connection(
    db: Session,
    user: User,
    connection: Connection,
    *,
    accept: bool,
) -> Connection:
    if connection.recipient_user_id != user.id:
        raise CommunityError("Only the recipient can answer this request.")
    new_status = (
        ConnectionStatus.ACCEPTED if accept else ConnectionStatus.DECLINED
    )
    result = db.execute(
        update(Connection)
        .where(
            Connection.id == connection.id,
            Connection.recipient_user_id == user.id,
            Connection.status == ConnectionStatus.PENDING,
        )
        .values(status=new_status, responded_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        db.rollback()
        raise CommunityError("This connection request has already been answered.")
    if accept:
        notify_connection(db, connection, accepted=True)
    from app.models.notifications import Notification

    db.execute(update(Notification).where(
        Notification.connection_id == connection.id, Notification.recipient_id == user.id,
    ).values(read_at=datetime.now(UTC)))
    db.commit()
    db.refresh(connection)
    return connection


def remove_connection(db: Session, user: User, connection: Connection) -> None:
    if user.id not in {
        connection.requester_user_id,
        connection.recipient_user_id,
    }:
        raise CommunityError("This connection does not belong to you.")
    db.delete(connection)
    db.commit()


def followed_user_ids(db: Session, user_id: UUID) -> set[UUID]:
    return set(
        db.scalars(
            select(Follow.followed_user_id).where(
                Follow.follower_user_id == user_id
            )
        ).all()
    )


def follow_exists(db: Session, follower_id: UUID, followed_id: UUID) -> bool:
    return (
        db.scalar(
            select(Follow.id).where(
                Follow.follower_user_id == follower_id,
                Follow.followed_user_id == followed_id,
            )
        )
        is not None
    )


def list_received_requests(db: Session, user_id: UUID) -> list[Connection]:
    return list(
        db.scalars(
            select(Connection)
            .where(
                Connection.recipient_user_id == user_id,
                Connection.status == ConnectionStatus.PENDING,
            )
            .order_by(Connection.created_at.desc())
        ).all()
    )


def list_connections(db: Session, user_id: UUID) -> list[Connection]:
    return list(
        db.scalars(
            select(Connection)
            .where(
                or_(
                    Connection.requester_user_id == user_id,
                    Connection.recipient_user_id == user_id,
                ),
                Connection.status == ConnectionStatus.ACCEPTED,
            )
            .order_by(Connection.responded_at.desc())
        ).all()
    )


def users_by_id(db: Session, user_ids: set[UUID]) -> dict[UUID, User]:
    if not user_ids:
        return {}
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
    return {user.id: user for user in users}


def public_profile_ids(
    db: Session,
    user_ids: set[UUID],
) -> dict[UUID, UUID]:
    if not user_ids:
        return {}
    profiles = db.scalars(
        select(NurseProfile).where(
            NurseProfile.user_id.in_(user_ids),
            NurseProfile.status == ProfileStatus.ACTIVE,
            NurseProfile.discoverable.is_(True),
        )
    ).all()
    return {profile.user_id: profile.public_id for profile in profiles}


def reconcile_community_media(db: Session, *, dry_run: bool = False) -> dict[str, int]:
    """Remove orphan files and reconcile retained-byte counters."""
    if not dry_run:
        from app.services.offline_uploads import cleanup

        cleanup(db)
    stale_media = list(
        db.scalars(
            select(CommunityMedia)
            .join(CommunityPost, CommunityMedia.post_id == CommunityPost.id)
            .where(CommunityPost.status == ContentStatus.REMOVED)
        ).all()
    )
    stale_names = {item.storage_name for item in stale_media}
    referenced_names = set(db.scalars(select(CommunityMedia.storage_name)).all())
    referenced_names -= stale_names
    removed = cleanup_orphan_community_media(
        referenced_names,
        dry_run=dry_run,
    )
    if not dry_run:
        for item in stale_media:
            db.delete(item)
    totals = dict(
        db.execute(
            select(
                CommunityPost.author_id,
                func.coalesce(func.sum(CommunityMedia.size_bytes), 0),
            )
            .join(CommunityMedia, CommunityMedia.post_id == CommunityPost.id)
            .group_by(CommunityPost.author_id)
        ).all()
    )
    corrected = 0
    users = db.scalars(select(User)).all()
    for user in users:
        expected = int(totals.get(user.id, 0))
        if user.community_storage_bytes != expected:
            corrected += 1
            if not dry_run:
                user.community_storage_bytes = expected
    if not dry_run:
        db.commit()
    return {
        "referenced_files": len(referenced_names),
        "removed_files": len(removed),
        "removed_media_records": len(stale_media),
        "corrected_accounts": corrected,
    }
