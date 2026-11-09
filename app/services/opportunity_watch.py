"""Private saves, explicit matching choices and durable opportunity notifications."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.jobs import Job
from app.models.notifications import Notification
from app.models.opportunities import OpportunityPreference, SavedOpportunity
from app.models.user import User, UserStatus
from app.services.jobs import JOB_TYPE_LABELS, JobError, open_job_condition
from app.services.notifications import emit
from app.services.recruitment import utc


def insert_for(db):
    return sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert


def saved_ids(db, user, ids):
    if not user:
        return set()
    return set(
        db.scalars(
            select(SavedOpportunity.job_id).where(
                SavedOpportunity.user_id == user.id, SavedOpportunity.job_id.in_(ids)
            )
        )
    )


def save_job(db, user, job, *, remind=True):
    if not db.scalar(select(Job.id).where(Job.id == job.id, open_job_condition())):
        raise JobError("This opportunity is no longer available to save.")
    statement = insert_for(db)(SavedOpportunity).values(
        user_id=user.id, job_id=job.id, remind=remind
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "job_id"],
            set_={"remind": remind, "updated_at": datetime.now(UTC)},
        )
    )
    db.commit()


def remove_saved(db, user, job_id):
    db.execute(
        delete(SavedOpportunity).where(
            SavedOpportunity.user_id == user.id, SavedOpportunity.job_id == job_id
        )
    )
    db.commit()


def match_conditions(preference):
    conditions = []
    if preference.country_code:
        conditions.append(Job.country_code == preference.country_code)
    if preference.job_type:
        conditions.append(Job.job_type == preference.job_type)
    if preference.keyword:
        conditions.append(
            or_(
                Job.title.icontains(preference.keyword, autoescape=True),
                Job.organization.icontains(preference.keyword, autoescape=True),
                Job.location.icontains(preference.keyword, autoescape=True),
            )
        )
    if preference.location:
        conditions.append(Job.location.icontains(preference.location, autoescape=True))
    return conditions


def preferences(db, user):
    return db.get(OpportunityPreference, user.id)


def save_preferences(db, user, *, keyword, location, job_type, country_code, enabled):
    keyword, location = keyword.strip(), location.strip()
    if len(keyword) > 120 or len(location) > 100:
        raise JobError("Keep the keyword within 120 characters and location within 100.")
    if job_type and job_type not in JOB_TYPE_LABELS:
        raise JobError("Choose an opportunity type.")
    if country_code not in {"NG", ""}:
        raise JobError("Choose Nigeria or all countries.")
    now = datetime.now(UTC)
    values = dict(
        keyword=keyword,
        location=location,
        job_type=job_type,
        country_code=country_code,
        enabled=enabled,
        next_check_at=now,
        active_since=now,
    )
    old = preferences(db, user)
    if old and all(
        getattr(old, key) == value
        for key, value in values.items()
        if key not in {"next_check_at", "active_since"}
    ):
        return
    db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.kind == "opportunity_match",
            Notification.email_state.in_(["queued", "sending"]),
        )
        .values(email_state="skipped", email_to="", email_lease_token=None, email_lease_until=None)
    )
    statement = insert_for(db)(OpportunityPreference).values(user_id=user.id, **values)
    db.execute(statement.on_conflict_do_update(index_elements=["user_id"], set_=values))
    db.commit()


def matching_jobs(db, user, *, before=None, limit=25):
    choice = preferences(db, user)
    query = select(Job).where(open_job_condition())
    if choice:
        query = query.where(*match_conditions(choice))
    else:
        query = query.where(Job.country_code == "NG")
    return list(
        db.scalars(
            query.order_by(
                case((Job.country_code == "NG", 0), else_=1), Job.posted_at.desc(), Job.id.desc()
            ).limit(limit)
        )
    )


def job_notice_access():
    """Shared display/delivery condition, reevaluated against current opportunity state."""
    current_save = (
        select(SavedOpportunity.job_id)
        .where(
            SavedOpportunity.user_id == Notification.recipient_id,
            SavedOpportunity.job_id == Notification.job_id,
            SavedOpportunity.remind.is_(True),
        )
        .correlate(Notification)
        .exists()
    )
    return (
        select(Job.id)
        .where(
            Job.id == Notification.job_id,
            open_job_condition(),
            or_(
                Notification.kind == "opportunity_match",
                and_(
                    Notification.kind == "deadline_reminder",
                    Job.closes_at == Notification.deadline_at,
                    current_save,
                ),
            ),
        )
        .correlate(Notification)
        .exists()
    )


def generate_alerts(db, *, now=None, limit=100):
    """Bounded, repeatable scans; notices and progress commit together."""
    now = now or datetime.now(UTC)
    active = and_(User.is_active.is_(True), User.status == UserStatus.ACTIVE)
    saved = list(
        db.execute(
            select(SavedOpportunity, Job, User)
            .join(Job, Job.id == SavedOpportunity.job_id)
            .join(User, User.id == SavedOpportunity.user_id)
            .where(
                active,
                SavedOpportunity.remind.is_(True),
                open_job_condition(),
                Job.closes_at > now,
                Job.closes_at <= now + timedelta(hours=48),
                or_(
                    SavedOpportunity.reminded_deadline.is_(None),
                    SavedOpportunity.reminded_deadline != Job.closes_at,
                ),
            )
            .order_by(Job.closes_at, SavedOpportunity.user_id, Job.id)
            .limit(limit)
        )
    )
    reminders = 0
    for saved_row, job, user in saved:
        previous = saved_row.reminded_deadline
        claimed = db.execute(
            update(SavedOpportunity)
            .where(
                SavedOpportunity.user_id == user.id,
                SavedOpportunity.job_id == job.id,
                SavedOpportunity.remind.is_(True),
                SavedOpportunity.reminded_deadline.is_(None)
                if previous is None
                else SavedOpportunity.reminded_deadline == previous,
            )
            .values(reminded_deadline=job.closes_at),
            execution_options={"synchronize_session": False},
        )
        if claimed.rowcount != 1:
            continue
        deadline = utc(job.closes_at)
        emit(
            db,
            actor_id=None,
            recipients={user.id},
            category="opportunities",
            kind="deadline_reminder",
            event_key=f"deadline:{job.id}:{deadline.isoformat()}",
            job_id=job.id,
            deadline_at=deadline,
        )
        reminders += 1
    # Flush reminder progress before the preferences claim query; both remain atomic.
    db.flush()
    choices = list(
        db.scalars(
            select(OpportunityPreference)
            .join(User)
            .where(
                active,
                OpportunityPreference.enabled.is_(True),
                OpportunityPreference.next_check_at <= now,
            )
            .order_by(OpportunityPreference.next_check_at, OpportunityPreference.user_id)
            .limit(50)
        )
    )
    matches = 0
    for choice in choices:
        changed = db.execute(
            update(OpportunityPreference)
            .where(
                OpportunityPreference.user_id == choice.user_id,
                OpportunityPreference.next_check_at == choice.next_check_at,
                OpportunityPreference.enabled.is_(True),
            )
            .values(next_check_at=now + timedelta(minutes=5)),
            execution_options={"synchronize_session": False},
        )
        if changed.rowcount != 1:
            continue
        existing = select(Notification.job_id).where(
            Notification.recipient_id == choice.user_id,
            Notification.kind == "opportunity_match",
            Notification.job_id.is_not(None),
        )
        jobs = db.scalars(
            select(Job)
            .where(
                open_job_condition(),
                *match_conditions(choice),
                Job.created_at >= choice.active_since,
                Job.id.not_in(existing),
            )
            .order_by(Job.created_at, Job.id)
            .limit(20)
        ).all()
        for job in jobs:
            emit(
                db,
                actor_id=None,
                recipients={choice.user_id},
                category="opportunities",
                kind="opportunity_match",
                event_key=f"match:{job.id}",
                job_id=job.id,
            )
            matches += 1
    db.commit()
    return {"reminders": reminders, "matches": matches}
