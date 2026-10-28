"""Community publishing, moderation, and member-relationship rules."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.community_storage import (
    CommunityStorageError,
    delete_community_media,
    save_community_media,
)
from app.models.community import (
    CommunityMedia,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    ConnectionStatus,
    ContentReport,
    ContentStatus,
    Follow,
    MediaKind,
    ReportReason,
    ReportStatus,
)
from app.models.profile import NurseProfile, ProfileStatus
from app.models.user import User

COMMUNITY_NAME_MAX = 80
POST_BODY_MAX = 5000
REPLY_BODY_MAX = 2000
TOPIC_NAME_MAX = 80
TOPIC_DESCRIPTION_MAX = 500
REPORT_DETAILS_MAX = 1000
MODERATION_NOTE_MAX = 1000
EXTERNAL_URL_MAX = 2048
MAX_IMAGES_PER_POST = 4

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
    data: bytes
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


def set_community_name(db: Session, user: User, name: str) -> User:
    """Set the name shown publicly beside posts and replies."""
    cleaned = _clean_text(
        name,
        field="Community name",
        maximum=COMMUNITY_NAME_MAX,
        required=True,
    )
    if len(cleaned) < 2:
        raise CommunityError("Community name must be at least 2 characters.")
    user.community_name = cleaned
    db.commit()
    db.refresh(user)
    return user


def _require_community_name(user: User) -> None:
    if not (user.community_name or "").strip():
        raise CommunityError(
            "Choose a public community name before posting or replying."
        )


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
) -> CommunityPost:
    """Run synchronous checks, store media, and publish one topic post."""
    _require_community_name(user)
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
        status=ContentStatus.PUBLISHED,
    )
    db.add(post)
    stored_names: list[str] = []
    uploads: list[tuple[str, CommunityUpload]] = [
        (MediaKind.IMAGE.value, upload) for upload in images
    ]
    if video is not None:
        uploads.append((MediaKind.VIDEO.value, video))

    try:
        for position, (kind, upload) in enumerate(uploads):
            storage_name, content_type, size_bytes, duration = save_community_media(
                upload.data, kind
            )
            stored_names.append(storage_name)
            post.media.append(
                CommunityMedia(
                    kind=kind,
                    original_filename=(upload.filename or "")[:255],
                    storage_name=storage_name,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    duration_seconds=duration,
                    position=position,
                )
            )
        db.commit()
    except (CommunityStorageError, SQLAlchemyError) as exc:
        db.rollback()
        for storage_name in stored_names:
            delete_community_media(storage_name)
        if isinstance(exc, CommunityStorageError):
            raise CommunityError(str(exc)) from None
        raise CommunityError("The post could not be published.") from None

    db.refresh(post)
    return post


def _post_load_options():
    return (
        selectinload(CommunityPost.author),
        selectinload(CommunityPost.topic),
        selectinload(CommunityPost.media),
        selectinload(CommunityPost.replies).selectinload(CommunityReply.author),
    )


def list_published_posts(
    db: Session,
    *,
    topic_id: UUID | None = None,
    author_ids: set[UUID] | None = None,
    limit: int = 50,
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
    statement = statement.options(*_post_load_options()).order_by(
        CommunityPost.published_at.desc(), CommunityPost.id.desc()
    )
    return list(db.scalars(statement.limit(limit)).all())


def get_published_post(db: Session, post_id: UUID) -> CommunityPost | None:
    return db.scalar(
        select(CommunityPost)
        .where(
            CommunityPost.id == post_id,
            CommunityPost.status == ContentStatus.PUBLISHED,
        )
        .options(*_post_load_options())
    )


def add_reply(
    db: Session,
    user: User,
    post: CommunityPost,
    body: str,
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
    reply = CommunityReply(
        post_id=post.id,
        author_id=user.id,
        body=cleaned,
        status=ContentStatus.PUBLISHED,
    )
    db.add(reply)
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
    if post.author_id == user.id:
        raise CommunityError("You cannot report your own post.")
    clean_reason, clean_details = _clean_report(reason, details)
    existing = db.scalar(
        select(ContentReport).where(
            ContentReport.reporter_id == user.id,
            ContentReport.post_id == post.id,
            ContentReport.status == ReportStatus.OPEN,
        )
    )
    if existing is not None:
        raise CommunityError("You already reported this post.")
    report = ContentReport(
        reporter_id=user.id,
        post_id=post.id,
        reason=clean_reason,
        details=clean_details,
    )
    db.add(report)
    db.commit()
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
    if reply.author_id == user.id:
        raise CommunityError("You cannot report your own reply.")
    clean_reason, clean_details = _clean_report(reason, details)
    existing = db.scalar(
        select(ContentReport).where(
            ContentReport.reporter_id == user.id,
            ContentReport.reply_id == reply.id,
            ContentReport.status == ReportStatus.OPEN,
        )
    )
    if existing is not None:
        raise CommunityError("You already reported this reply.")
    report = ContentReport(
        reporter_id=user.id,
        reply_id=reply.id,
        reason=clean_reason,
        details=clean_details,
    )
    db.add(report)
    db.commit()
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
    if report.status != ReportStatus.OPEN:
        raise CommunityError("This report has already been reviewed.")
    if action not in {"remove", "dismiss"}:
        raise CommunityError("Choose remove or dismiss.")
    clean_note = _clean_text(
        note,
        field="Moderation note",
        maximum=MODERATION_NOTE_MAX,
        required=True,
    )
    now = datetime.now(UTC)
    report.reviewed_by_user_id = staff.id
    report.reviewed_at = now
    report.review_note = clean_note

    if action == "remove":
        target = report.post or report.reply
        if target is None:
            raise CommunityError("The reported content no longer exists.")
        target.status = ContentStatus.REMOVED
        target.removed_by_user_id = staff.id
        target.removed_at = now
        target.removal_reason = clean_note
        report.status = ReportStatus.RESOLVED
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
            )
        )
    else:
        report.status = ReportStatus.DISMISSED
    db.commit()
    db.refresh(report)
    return report


def get_public_media(db: Session, media_id: UUID) -> CommunityMedia | None:
    return db.scalar(
        select(CommunityMedia)
        .join(CommunityPost, CommunityMedia.post_id == CommunityPost.id)
        .where(
            CommunityMedia.id == media_id,
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
    existing = connection_between(db, user.id, profile.user_id)
    if existing is not None:
        if existing.status == ConnectionStatus.DECLINED:
            existing.requester_user_id = user.id
            existing.recipient_user_id = profile.user_id
            existing.status = ConnectionStatus.PENDING
            existing.responded_at = None
            db.commit()
            db.refresh(existing)
        return existing
    item = Connection(
        requester_user_id=user.id,
        recipient_user_id=profile.user_id,
        status=ConnectionStatus.PENDING,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def connection_between(
    db: Session,
    first_user_id: UUID,
    second_user_id: UUID,
) -> Connection | None:
    return db.scalar(
        select(Connection).where(
            or_(
                and_(
                    Connection.requester_user_id == first_user_id,
                    Connection.recipient_user_id == second_user_id,
                ),
                and_(
                    Connection.requester_user_id == second_user_id,
                    Connection.recipient_user_id == first_user_id,
                ),
            )
        )
    )


def respond_to_connection(
    db: Session,
    user: User,
    connection: Connection,
    *,
    accept: bool,
) -> Connection:
    if connection.recipient_user_id != user.id:
        raise CommunityError("Only the recipient can answer this request.")
    if connection.status != ConnectionStatus.PENDING:
        raise CommunityError("This connection request has already been answered.")
    connection.status = (
        ConnectionStatus.ACCEPTED if accept else ConnectionStatus.DECLINED
    )
    connection.responded_at = datetime.now(UTC)
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
