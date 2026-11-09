"""Account usage counts, independent of public profiles and notification polling."""

import logging
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, and_, case, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.activity import UserDailyActivity as Activity
from app.models.user import User, UserStatus

logger = logging.getLogger(__name__)
NIGERIA = ZoneInfo("Africa/Lagos")
RECENT_WINDOW = timedelta(minutes=5)
WRITE_INTERVAL = timedelta(seconds=60)
PAGE_SIZE = 25
ACCOUNT_TYPES = {
    "nurse": "Nurse accounts",
    "employer": "Employer accounts",
    "partner": "Partner accounts",
    "all": "All accounts",
}
ACTIVITY_FILTERS = {
    "all": "Any activity",
    "recent": "Last 5 minutes",
    "today": "Today",
    "week": "Last 7 days",
    "month": "Last 30 days",
    "never": "No recorded activity",
}


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def local_day(value: datetime) -> date:
    return utc(value).astimezone(NIGERIA).date()


def day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, NIGERIA).astimezone(UTC)


def local_time(value: datetime | None) -> str:
    return utc(value).astimezone(NIGERIA).strftime("%d %b %Y · %H:%M WAT") if value else ""


def record_activity(db, user_id: UUID, auth_version: int, *, at: datetime | None = None) -> bool:
    """Atomic, monotonic upsert; the caller owns this activity-only transaction.

    Server time and authenticated identity are the only inputs. The SELECT in the
    insert rechecks account/session eligibility, including deletion and revocation.
    The primary key deduplicates devices, concurrent requests and worker processes.
    """
    timestamp = utc(at or now())
    day = local_day(timestamp)
    previous = db.execute(
        select(Activity.first_seen_at, Activity.last_seen_at).where(
            Activity.user_id == user_id, Activity.activity_date == day
        )
    ).one_or_none()
    if (
        previous
        and utc(previous.first_seen_at) <= timestamp
        and (utc(previous.last_seen_at) > timestamp - WRITE_INTERVAL)
    ):
        return False
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(Activity).from_select(
        ["user_id", "activity_date", "first_seen_at", "last_seen_at"],
        select(
            User.id,
            literal(day, Date()),
            literal(timestamp, DateTime(timezone=True)),
            literal(timestamp, DateTime(timezone=True)),
        ).where(
            User.id == user_id,
            User.auth_version == auth_version,
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        ),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Activity.user_id, Activity.activity_date],
        set_={
            "first_seen_at": case(
                (Activity.first_seen_at > timestamp, timestamp), else_=Activity.first_seen_at
            ),
            "last_seen_at": case(
                (Activity.last_seen_at < timestamp, timestamp), else_=Activity.last_seen_at
            ),
        },
        where=or_(
            Activity.last_seen_at <= timestamp - WRITE_INTERVAL,
            Activity.first_seen_at > timestamp,
        ),
    )
    return bool(db.execute(statement).rowcount)


def record_visit(db, user) -> bool:
    """Never commit/rollback the route's business transaction or fail its page.

    Use the same database engine (including dependency overrides), but a separate
    short transaction. Do not log SQL, request details, credentials or identity.
    """
    try:
        bind = db.get_bind()
        with Session(bind=bind.engine) as activity_db:
            record_activity(activity_db, user.id, user.auth_version)
            activity_db.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Account activity could not be recorded (%s).", type(exc).__name__)
        return False


def _scope(account_type, include_staff):
    return and_(
        User.account_type == account_type if account_type != "all" else literal(True),
        literal(True) if include_staff else User.is_staff.is_(False),
    )


def activity_report(db, *, account_type="nurse", include_staff=False, days=14, at=None):
    timestamp = utc(at or now())
    today = local_day(timestamp)
    week_start, month_start = today - timedelta(days=6), today - timedelta(days=29)
    scope = _scope(account_type, include_staff)
    period = db.execute(
        select(
            func.count(func.distinct(case((Activity.activity_date == today, User.id)))),
            func.count(func.distinct(case((Activity.activity_date >= week_start, User.id)))),
            func.count(func.distinct(User.id)),
        )
        .select_from(Activity)
        .join(User, User.id == Activity.user_id)
        .where(
            scope,
            Activity.activity_date >= month_start,
            Activity.activity_date <= today,
            Activity.first_seen_at <= timestamp,
        )
    ).one()
    recent = db.scalar(
        select(func.count(func.distinct(Activity.user_id)))
        .join(User)
        .where(
            scope,
            Activity.last_seen_at >= timestamp - RECENT_WINDOW,
            Activity.last_seen_at <= timestamp,
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    )
    first_record = db.scalar(select(func.min(Activity.first_seen_at)))
    start = (
        max(today - timedelta(days=days - 1), local_day(first_record)) if first_record else today
    )
    daily_counts = dict(
        db.execute(
            select(Activity.activity_date, func.count(Activity.user_id))
            .join(User)
            .where(
                scope,
                Activity.activity_date >= start,
                Activity.activity_date <= today,
                Activity.first_seen_at <= timestamp,
            )
            .group_by(Activity.activity_date)
        ).all()
    )
    history = (
        [
            {
                "date": today - timedelta(days=offset),
                "count": daily_counts.get(today - timedelta(days=offset), 0),
            }
            for offset in range((today - start).days + 1)
        ]
        if first_record
        else []
    )
    total = db.scalar(select(func.count(User.id)).where(scope))
    enabled = db.scalar(
        select(func.count(User.id)).where(
            scope,
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    )
    return {
        "total": total,
        "enabled": enabled,
        "today": period[0],
        "week": period[1],
        "month": period[2],
        "recent": recent,
        "date": today,
        "as_of": local_time(timestamp),
        "history": history,
        "first_record": local_time(first_record),
        "participation": round(period[0] / total * 100, 1) if total else 0,
    }


def member_activity(
    db, *, account_type="nurse", include_staff=False, query="", activity="all", page=1, at=None
):
    timestamp = utc(at or now())
    today = local_day(timestamp)
    records = (
        select(
            Activity.user_id,
            func.max(Activity.last_seen_at).label("last_seen"),
            func.count(
                case(
                    (
                        and_(
                            Activity.activity_date >= today - timedelta(days=29),
                            Activity.activity_date <= today,
                        ),
                        1,
                    )
                )
            ).label("days_active"),
        )
        .group_by(Activity.user_id)
        .subquery()
    )
    statement = (
        select(User, records.c.last_seen, records.c.days_active)
        .outerjoin(records, records.c.user_id == User.id)
        .where(_scope(account_type, include_staff))
    )
    if query:
        matches = [
            User.full_name.icontains(query, autoescape=True),
            User.community_name.icontains(query, autoescape=True),
        ]
        try:
            matches.append(User.id == UUID(query))
        except ValueError:
            pass
        statement = statement.where(or_(*matches))
    if activity == "never":
        statement = statement.where(records.c.last_seen.is_(None))
    elif activity != "all":
        cutoff = (
            timestamp - RECENT_WINDOW
            if activity == "recent"
            else day_start(today - timedelta(days={"today": 0, "week": 6, "month": 29}[activity]))
        )
        statement = statement.where(records.c.last_seen >= cutoff, records.c.last_seen <= timestamp)
        if activity == "recent":
            statement = statement.where(User.is_active.is_(True), User.status == UserStatus.ACTIVE)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(page, pages)
    rows = db.execute(
        statement.order_by(records.c.last_seen.desc().nulls_last(), User.created_at.desc(), User.id)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    cards = []
    for user, last_seen, days_active in rows:
        enabled = user.is_active and user.status == UserStatus.ACTIVE
        recent = bool(
            enabled and last_seen and timestamp - RECENT_WINDOW <= utc(last_seen) <= timestamp
        )
        cards.append(
            {
                "user": user,
                "name": user.full_name or user.community_name or "Unnamed account",
                "last_seen": utc(last_seen) if last_seen else None,
                "last_seen_label": local_time(last_seen),
                "recent": recent,
                "activity_label": "Last 5 minutes"
                if recent
                else (
                    "Today"
                    if last_seen and local_day(last_seen) == today
                    else "Earlier activity"
                    if last_seen
                    else "No recorded activity"
                ),
                "account_status": "Enabled"
                if enabled
                else ("Suspended" if user.status == UserStatus.SUSPENDED else "Deactivated"),
                "days_active": days_active or 0,
            }
        )
    return {"cards": cards, "total": total, "page": page, "pages": pages}
