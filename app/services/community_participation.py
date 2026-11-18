"""Newcomer welcomes, recurring activities and private participation records."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, or_, select, update

from app.models.community import (
    CommunityMembership,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    ContentStatus,
    DiscussionFollow,
    HelpfulReply,
)
from app.models.participation import (
    ActivityAttendance,
    ActivityOccurrence,
    ActivitySeries,
    CommunityIntroduction,
    MemberJourney,
)
from app.models.user import User, UserStatus
from app.services.community import CommunityError, create_post, get_published_post
from app.services.community_growth import ACTIVITY_FORMATS, _active, _insert, can_manage_community
from app.services.notifications import emit

GOALS = {
    "school": "Find my feet in nursing school",
    "study": "Prepare for examinations",
    "practice": "Build confidence in clinical practice",
    "career": "Explore my next career step",
    "research": "Connect around research and postgraduate study",
    "teaching": "Share teaching and nursing education",
    "community": "Meet colleagues and support others",
}
TIMEZONES = {
    "Africa/Lagos": "Nigeria (WAT)",
    "UTC": "UTC",
    "Europe/London": "London",
    "America/New_York": "New York",
}


def utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def recognition_summaries(db, author_ids):
    if not author_ids:
        return {}
    rows = db.execute(
        select(CommunityReply.author_id, func.count())
        .join(HelpfulReply, HelpfulReply.reply_id == CommunityReply.id)
        .join(CommunityPost)
        .join(CommunityTopic)
        .join(MemberJourney, MemberJourney.user_id == CommunityReply.author_id)
        .join(User, User.id == HelpfulReply.user_id)
        .where(
            CommunityReply.author_id.in_(author_ids),
            MemberJourney.show_recognition.is_(True),
            CommunityReply.status == ContentStatus.PUBLISHED,
            CommunityPost.status == ContentStatus.PUBLISHED,
            CommunityTopic.is_active.is_(True),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
        .group_by(CommunityReply.author_id)
    )
    return dict(rows.all())


def zone(value):
    try:
        if len(value) > 64:
            raise ValueError
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise CommunityError("Choose a valid timezone.") from None


def save_journey(db, user, *, goal="", show_recognition=False, dismiss=False):
    _active(user)
    if goal and goal not in GOALS:
        raise CommunityError("Choose one of the listed goals.")
    db.execute(
        _insert(db)(MemberJourney)
        .values(
            user_id=user.id,
            goal=goal,
            show_recognition=show_recognition,
            dismissed_at=datetime.now(UTC) if dismiss else None,
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "goal": goal,
                "show_recognition": show_recognition,
                "dismissed_at": datetime.now(UTC) if dismiss else None,
            },
        )
    )
    db.commit()


def progress(db, user):
    journey = db.get(MemberJourney, user.id)
    joined = (
        db.scalar(
            select(func.count())
            .select_from(CommunityMembership)
            .join(CommunityTopic, CommunityTopic.id == CommunityMembership.topic_id)
            .where(CommunityMembership.user_id == user.id, CommunityTopic.is_active.is_(True))
        )
        or 0
    )
    posts = (
        db.scalar(
            select(func.count())
            .select_from(CommunityPost)
            .join(CommunityTopic)
            .where(
                CommunityPost.author_id == user.id,
                CommunityPost.status == ContentStatus.PUBLISHED,
                CommunityTopic.is_active.is_(True),
            )
        )
        or 0
    )
    replies = (
        db.scalar(
            select(func.count())
            .select_from(CommunityReply)
            .join(CommunityPost)
            .join(CommunityTopic)
            .where(
                CommunityReply.author_id == user.id,
                CommunityReply.status == ContentStatus.PUBLISHED,
                CommunityPost.status == ContentStatus.PUBLISHED,
                CommunityTopic.is_active.is_(True),
            )
        )
        or 0
    )
    helpful = (
        db.scalar(
            select(func.count())
            .select_from(HelpfulReply)
            .join(CommunityReply)
            .join(CommunityPost)
            .join(CommunityTopic)
            .join(User, User.id == HelpfulReply.user_id)
            .where(
                CommunityReply.author_id == user.id,
                CommunityReply.status == ContentStatus.PUBLISHED,
                CommunityPost.status == ContentStatus.PUBLISHED,
                CommunityTopic.is_active.is_(True),
                User.is_active.is_(True),
                User.status == UserStatus.ACTIVE,
            )
        )
        or 0
    )
    return {
        "journey": journey,
        "joined": joined,
        "posts": posts,
        "replies": replies,
        "helpful": helpful,
        "introduced": db.scalar(
            select(CommunityIntroduction.post_id)
            .join(CommunityPost)
            .where(
                CommunityIntroduction.user_id == user.id,
                CommunityPost.status == ContentStatus.PUBLISHED,
            )
        ),
    }


def introduce(db, user, *, topic_id, body):
    _active(user)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(
        select(CommunityIntroduction).where(CommunityIntroduction.user_id == user.id)
    )
    if existing:
        if get_published_post(db, existing.post_id):
            return db.get(CommunityPost, existing.post_id)
        raise CommunityError("Your previous introduction is unavailable. Start a new conversation.")
    post = create_post(
        db, user, topic_id=topic_id, body=body, title="Meet a new colleague", commit=False
    )
    db.add(CommunityIntroduction(post_id=post.id, user_id=user.id))
    db.execute(
        _insert(db)(CommunityMembership)
        .values(user_id=user.id, topic_id=post.topic_id)
        .on_conflict_do_nothing()
    )
    emit(
        db,
        actor_id=user.id,
        recipients={post.topic.created_by_user_id},
        category="community",
        kind="introduction",
        event_key=f"introduction:{post.id}",
        post_id=post.id,
    )
    db.commit()
    return post


def welcome_queue(db, user, topic, *, page=1):
    if not can_manage_community(user, topic):
        raise CommunityError("Only the community host or staff can view its welcome queue.")
    return list(
        db.scalars(
            select(CommunityPost)
            .join(CommunityIntroduction)
            .where(
                CommunityPost.topic_id == topic.id,
                CommunityPost.status == ContentStatus.PUBLISHED,
                CommunityIntroduction.host_welcome.is_(False),
            )
            .order_by(CommunityPost.published_at, CommunityPost.id)
            .offset((page - 1) * 20)
            .limit(21)
        )
    )


def acknowledge_welcome(db, user, post_id):
    post = get_published_post(db, post_id)
    if not post or not can_manage_community(user, post.topic):
        raise CommunityError("Only the community host or staff can welcome this member.")
    # Mark after a real public reply from this host, not a fabricated greeting.
    if not db.scalar(
        select(CommunityReply.id).where(
            CommunityReply.post_id == post.id,
            CommunityReply.author_id == user.id,
            CommunityReply.status == ContentStatus.PUBLISHED,
        )
    ):
        raise CommunityError("Reply to the introduction before marking the welcome complete.")
    db.execute(
        update(CommunityIntroduction)
        .where(CommunityIntroduction.post_id == post.id)
        .values(host_welcome=True)
    )
    db.commit()


def next_start(value, interval, timezone):
    # Preserve local wall-clock time through seasonal timezone changes.
    return (utc(value).astimezone(zone(timezone)) + timedelta(days=interval)).astimezone(UTC)


def create_series(
    db,
    user,
    *,
    identifier,
    topic_id,
    title,
    instructions,
    activity_format,
    starts_at,
    timezone="Africa/Lagos",
    interval=7,
    now=None,
):
    _active(user)
    if interval not in {7, 14, 28} or activity_format not in ACTIVITY_FORMATS:
        raise CommunityError("Choose a valid activity format and repeat interval.")
    try:
        identifier = UUID(str(identifier))
        raw = datetime.fromisoformat(starts_at)
        if raw.tzinfo is not None:
            raise ValueError
        starts = raw.replace(tzinfo=zone(timezone)).astimezone(UTC)
        # Reject nonexistent local times during clock changes.
        if starts.astimezone(zone(timezone)).replace(tzinfo=None) != raw:
            raise ValueError
    except (ValueError, TypeError):
        raise CommunityError("Enter a valid local date and time for the activity.") from None
    if starts <= (now or datetime.now(UTC)):
        raise CommunityError("Choose a future time for the first activity.")
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.get(ActivitySeries, identifier)
    if existing:
        if existing.host_id == user.id:
            return existing
        raise CommunityError("This activity form is unavailable. Open a new form.")
    count = (
        db.scalar(
            select(func.count())
            .select_from(ActivitySeries)
            .where(ActivitySeries.host_id == user.id, ActivitySeries.active.is_(True))
        )
        or 0
    )
    if count >= 10:
        raise CommunityError("You already host ten active series. Pause one before adding another.")
    post = create_post(
        db,
        user,
        topic_id=topic_id,
        body=instructions,
        post_kind="activity",
        title=title,
        activity_format=activity_format,
        activity_starts_at=starts.isoformat(),
        commit=False,
    )
    series = ActivitySeries(
        id=identifier,
        topic_id=post.topic_id,
        host_id=user.id,
        title=post.title,
        instructions=post.body,
        activity_format=activity_format,
        interval_days=interval,
        timezone=timezone,
        next_starts_at=next_start(starts, interval, timezone),
    )
    db.add(series)
    db.flush()
    db.add(ActivityOccurrence(series_id=series.id, starts_at=starts, post_id=post.id))
    db.commit()
    return series


def set_series_active(db, user, identifier, active):
    _active(user)
    series = db.get(ActivitySeries, identifier)
    if not series or (
        series.host_id != user.id
        and not can_manage_community(user, db.get(CommunityTopic, series.topic_id))
    ):
        raise CommunityError("Only the activity host or community host can manage this series.")
    series.active = active
    # On resume generate the next scheduled future occurrence; never backfill old sessions.
    now = datetime.now(UTC)
    if active:
        series.next_starts_at = advance(series.next_starts_at, series, now)
    db.commit()


def advance(value, series, now):
    value = utc(value)
    # Jump close to today first, then preserve wall-clock time through DST.
    local = value.astimezone(zone(series.timezone))
    days = (now.astimezone(zone(series.timezone)).date() - local.date()).days
    if days > series.interval_days:
        local += timedelta(days=(days // series.interval_days) * series.interval_days)
        value = local.astimezone(UTC)
    while value <= now:
        value = next_start(value, series.interval_days, series.timezone)
    return value


def run_next_activity(db, *, now=None):
    now = now or datetime.now(UTC)
    # Prepare sessions one day before they start so members can join in advance.
    series = db.scalar(
        select(ActivitySeries)
        .where(
            ActivitySeries.active.is_(True),
            ActivitySeries.next_starts_at <= now + timedelta(days=1),
        )
        .order_by(ActivitySeries.next_starts_at, ActivitySeries.id)
        .limit(1)
        .with_for_update()
    )
    if series is None:
        return None
    host = db.get(User, series.host_id)
    topic = db.get(CommunityTopic, series.topic_id)
    if not topic.is_active or not host.is_active or host.status != UserStatus.ACTIVE:
        series.active = False
        db.commit()
        return series.id, "paused"
    starts = utc(series.next_starts_at)
    future = advance(starts, series, now + timedelta(days=1))
    # A conditional update fences competing workers even on SQLite.
    changed = db.execute(
        update(ActivitySeries)
        .where(
            ActivitySeries.id == series.id,
            ActivitySeries.active.is_(True),
            ActivitySeries.next_starts_at == starts,
        )
        .values(next_starts_at=future)
    )
    if changed.rowcount != 1:
        db.rollback()
        return None
    if starts < now - timedelta(days=1):
        db.commit()
        return series.id, "missed"
    post = create_post(
        db,
        host,
        topic_id=series.topic_id,
        body=series.instructions,
        post_kind="activity",
        title=series.title,
        activity_format=series.activity_format,
        activity_starts_at=starts.isoformat(),
        commit=False,
    )
    db.add(ActivityOccurrence(series_id=series.id, starts_at=starts, post_id=post.id))
    # Only participants in the previous occurrence receive the next-session notice.
    previous = db.scalar(
        select(ActivityOccurrence.post_id)
        .where(ActivityOccurrence.series_id == series.id, ActivityOccurrence.starts_at < starts)
        .order_by(ActivityOccurrence.starts_at.desc())
        .limit(1)
    )
    if previous:
        recipients = set(
            db.scalars(
                select(ActivityAttendance.user_id).where(ActivityAttendance.post_id == previous)
            )
        )
        emit(
            db,
            actor_id=host.id,
            recipients=recipients,
            category="community",
            kind="activity",
            event_key=f"activity:{post.id}",
            post_id=post.id,
        )
    db.commit()
    return series.id, "published"


def attendance(db, user, post_id, *, attending):
    _active(user)
    post = get_published_post(db, post_id)
    if not post or post.post_kind != "activity":
        raise CommunityError("This learning activity is unavailable.")
    if attending:
        db.execute(
            _insert(db)(ActivityAttendance)
            .values(user_id=user.id, post_id=post.id)
            .on_conflict_do_nothing()
        )
        db.execute(
            _insert(db)(DiscussionFollow)
            .values(user_id=user.id, post_id=post.id, last_read_at=datetime.now(UTC))
            .on_conflict_do_nothing(index_elements=["user_id", "post_id"])
        )
    else:
        db.execute(
            delete(ActivityAttendance).where(
                ActivityAttendance.user_id == user.id, ActivityAttendance.post_id == post.id
            )
        )
    db.commit()


def activity_details(db, post, user):
    if post.post_kind != "activity":
        return {}
    count = (
        db.scalar(
            select(func.count())
            .select_from(ActivityAttendance)
            .join(User, User.id == ActivityAttendance.user_id)
            .where(
                ActivityAttendance.post_id == post.id,
                User.is_active.is_(True),
                User.status == UserStatus.ACTIVE,
            )
        )
        or 0
    )
    occurrence = db.scalar(select(ActivityOccurrence).where(ActivityOccurrence.post_id == post.id))
    return {
        "count": count,
        "attending": bool(user and db.get(ActivityAttendance, (post.id, user.id))),
        "series": db.get(ActivitySeries, occurrence.series_id) if occurrence else None,
    }


def series_list(db, user, *, page=1):
    return list(
        db.scalars(
            select(ActivitySeries)
            .join(CommunityTopic)
            .where(
                CommunityTopic.is_active.is_(True),
                or_(
                    ActivitySeries.host_id == user.id,
                    CommunityTopic.created_by_user_id == user.id,
                    user.is_staff,
                ),
            )
            .order_by(ActivitySeries.created_at.desc(), ActivitySeries.id)
            .offset((page - 1) * 20)
            .limit(21)
        )
    )
