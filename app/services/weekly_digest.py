"""Opt-in weekly highlights with durable claims and live eligibility checks.

Email requires verified-address opt-in. Receipts are per account/local week,
store no content snapshot, and recheck current membership/content before sending.
Changing preferences cancels queued claims; terminal receipts have bounded
retention. SMTP acceptance followed by a crash can still cause a retry.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import and_, delete, or_, select, update

from app.core.config import settings
from app.core.public_urls import public_site_ready, public_url
from app.models.community import CommunityMembership, CommunityPost, CommunityTopic, ContentStatus
from app.models.participation import DigestPreference, WeeklyDigest
from app.models.user import User, UserStatus
from app.services.account_mail import MailUnavailable, deliver_mail
from app.services.community import CommunityError
from app.services.community_growth import _active, _insert
from app.services.community_participation import utc, zone
from app.services.member_discovery import suggested_opportunities

MAX_ATTEMPTS = 5


def next_due(now, weekday, timezone):
    local = utc(now).astimezone(zone(timezone))
    due = local.replace(hour=9, minute=0, second=0, microsecond=0)
    due += timedelta(days=(weekday - local.weekday()) % 7)
    if due <= local:
        due += timedelta(days=7)
    return due.astimezone(UTC)


def save_preferences(
    db,
    user,
    *,
    enabled=False,
    questions=False,
    activities=False,
    opportunities=False,
    weekday=0,
    timezone="Africa/Lagos",
    now=None,
):
    """Persist verified-email opt-in/scheduling choices and cancel superseded queued claims."""
    _active(user)
    if weekday not in range(7):
        raise CommunityError("Choose a delivery day.")
    zone(timezone)
    if enabled and not (questions or activities or opportunities):
        raise CommunityError("Choose at least one type of highlight.")
    if enabled and not (user.email and user.email_verified_at):
        raise CommunityError("Verify your email in Settings before enabling the weekly digest.")
    pref = db.scalar(
        select(DigestPreference).where(DigestPreference.user_id == user.id).with_for_update()
    )
    values = dict(
        enabled=enabled,
        questions=questions,
        activities=activities,
        opportunities=opportunities,
        weekday=weekday,
        timezone=timezone,
        next_due_at=next_due(now or datetime.now(UTC), weekday, timezone) if enabled else None,
    )
    if pref is None:
        pref = DigestPreference(user_id=user.id, unsubscribe_hash=secrets.token_hex(32), **values)
        db.add(pref)
    else:
        for key, value in values.items():
            setattr(pref, key, value)
    # A changed subscription invalidates every queued claim before any retry.
    db.execute(
        update(WeeklyDigest)
        .where(WeeklyDigest.user_id == user.id, WeeklyDigest.state.in_(["queued", "sending"]))
        .values(state="skipped", lease_token=None, lease_until=None)
    )
    db.commit()
    return pref


def unsubscribe_token(pref):
    import hmac

    return hmac.new(
        settings.secret_key.encode(),
        f"{pref.user_id}:{pref.unsubscribe_hash}".encode(),
        hashlib.sha256,
    ).hexdigest()


def unsubscribe(db, identifier, token):
    import hmac

    pref = db.get(DigestPreference, identifier)
    if not pref or len(token) != 64 or not hmac.compare_digest(token, unsubscribe_token(pref)):
        return False
    pref.enabled = False
    pref.next_due_at = None
    db.execute(
        update(WeeklyDigest)
        .where(WeeklyDigest.user_id == identifier, WeeklyDigest.state.in_(["queued", "sending"]))
        .values(state="skipped", lease_token=None, lease_until=None)
    )
    db.commit()
    return True


def enqueue(db, *, now=None):
    """Create at most one eligible digest receipt per account and local calendar week."""
    now = now or datetime.now(UTC)
    prefs = list(
        db.scalars(
            select(DigestPreference)
            .where(DigestPreference.enabled.is_(True), DigestPreference.next_due_at <= now)
            .order_by(DigestPreference.next_due_at, DigestPreference.user_id)
            .limit(20)
        )
    )
    for pref in prefs:
        due = utc(pref.next_due_at)
        # Key the actual local week, so changing weekday cannot send twice in that week.
        iso = now.astimezone(zone(pref.timezone)).isocalendar()
        week = f"{iso.year}-{iso.week:02}"
        changed = db.execute(
            update(DigestPreference)
            .where(
                DigestPreference.user_id == pref.user_id,
                DigestPreference.enabled.is_(True),
                DigestPreference.next_due_at == due,
            )
            .values(next_due_at=next_due(now, pref.weekday, pref.timezone))
        )
        if changed.rowcount == 1:
            db.execute(
                _insert(db)(WeeklyDigest)
                .values(user_id=pref.user_id, week_key=week, next_attempt_at=now)
                .on_conflict_do_nothing(index_elements=["user_id", "week_key"])
            )
    db.commit()
    return len(prefs)


def highlights(db, user, pref, *, now=None):
    """Select currently accessible joined-community and opportunity facts without storing a mail
    snapshot.
    """
    now = now or datetime.now(UTC)
    statement = (
        select(CommunityPost)
        .join(CommunityTopic)
        .join(CommunityMembership, CommunityMembership.topic_id == CommunityTopic.id)
        .where(
            CommunityMembership.user_id == user.id,
            CommunityTopic.is_active.is_(True),
            CommunityPost.status == ContentStatus.PUBLISHED,
        )
    )
    rows = []
    if pref.questions:
        from app.models.community import CommunityReply

        unanswered = (
            ~select(CommunityReply.id)
            .where(
                CommunityReply.post_id == CommunityPost.id,
                CommunityReply.author_id != CommunityPost.author_id,
                CommunityReply.status == ContentStatus.PUBLISHED,
            )
            .correlate(CommunityPost)
            .exists()
        )
        posts = db.scalars(
            statement.where(
                CommunityPost.post_kind == "question",
                unanswered,
                CommunityPost.published_at >= now - timedelta(days=7),
            )
            .order_by(CommunityPost.published_at.desc(), CommunityPost.id)
            .limit(4)
        )
        rows += [
            {
                "kind": "Question",
                "title": post.title or post.body[:120],
                "path": f"/posts/{post.id}",
            }
            for post in posts
        ]
    if pref.activities:
        posts = db.scalars(
            statement.where(
                CommunityPost.post_kind == "activity",
                CommunityPost.activity_starts_at >= now,
                CommunityPost.activity_starts_at <= now + timedelta(days=7),
            )
            .order_by(CommunityPost.activity_starts_at, CommunityPost.id)
            .limit(4)
        )
        rows += [
            {"kind": "Learning together", "title": post.title, "path": f"/posts/{post.id}"}
            for post in posts
        ]
    if pref.opportunities:
        jobs, _ = suggested_opportunities(db, user, limit=4)
        rows += [
            {"kind": "Opportunity", "title": job["title"], "path": f"/jobs/{job['id']}"}
            for job in jobs
        ]
    return rows


def ready(now):
    return or_(
        and_(WeeklyDigest.state == "queued", WeeklyDigest.next_attempt_at <= now),
        and_(WeeklyDigest.state == "sending", WeeklyDigest.lease_until <= now),
    )


def eligible(db, item, token):
    pref = db.get(DigestPreference, item.user_id)
    user = db.get(User, item.user_id)
    return (
        pref,
        user,
        bool(
            pref
            and pref.enabled
            and user
            and user.email_verified_at
            and user.email
            and user.is_active
            and user.status == UserStatus.ACTIVE
            and public_site_ready()
            and item.lease_token == token
            and item.state == "sending"
        ),
    )


def run_next(db, *, now=None):
    """Claim one weekly digest and recheck eligibility/content before optional SMTP delivery."""
    now = now or datetime.now(UTC)
    identifier = db.scalar(
        select(WeeklyDigest.id)
        .where(ready(now))
        .order_by(WeeklyDigest.next_attempt_at, WeeklyDigest.id)
        .limit(1)
    )
    if identifier is None:
        return None
    token = uuid.uuid4().hex
    changed = db.execute(
        update(WeeklyDigest)
        .where(WeeklyDigest.id == identifier, ready(now))
        .values(state="sending", lease_token=token, lease_until=now + timedelta(seconds=120))
    )
    db.commit()
    if changed.rowcount != 1:
        return None
    db.expire_all()
    item = db.get(WeeklyDigest, identifier)
    pref, user, allowed = eligible(db, item, token)
    rows = highlights(db, user, pref, now=now) if allowed else []
    state = "skipped"
    if rows and item.attempts < MAX_ATTEMPTS:
        item.attempts += 1
        db.commit()
        db.expire_all()
        item = db.get(WeeklyDigest, identifier)
        pref, user, allowed = eligible(db, item, token)
        # Rebuild from live records after persisting the attempt.
        rows = highlights(db, user, pref, now=now) if allowed else []
        if allowed and rows:
            mail = EmailMessage()
            mail["From"] = settings.smtp_from or "Nurse.ng <no-reply@localhost>"
            mail["To"] = user.email
            mail["Subject"] = "Your week in the Nurse.ng community"
            mail["Message-ID"] = f"<digest-{item.id.hex}@nurse.ng>"
            off = public_url(f"/digest/unsubscribe/{pref.user_id}/{unsubscribe_token(pref)}")
            mail["List-Unsubscribe"] = f"<{off}>"
            mail["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            mail.set_content(
                "Your chosen community highlights\n\n"
                + "\n\n".join(
                    f"{row['kind']}: {row['title']}\n{public_url(row['path'])}" for row in rows
                )
                + f"\n\nManage your weekly digest: {public_url('/digest')}"
                + f"\nUnsubscribe: {off}\n"
            )
            try:
                deliver_mail(mail)
                state = "sent"
            except MailUnavailable:
                state = "failed" if item.attempts >= MAX_ATTEMPTS else "queued"
    elif rows:
        state = "failed"
    db.execute(
        update(WeeklyDigest)
        .where(
            WeeklyDigest.id == identifier,
            WeeklyDigest.state == "sending",
            WeeklyDigest.lease_token == token,
        )
        .values(
            state=state,
            lease_token=None,
            lease_until=None,
            sent_at=now if state == "sent" else None,
            next_attempt_at=now + timedelta(seconds=60 * 2**item.attempts),
        )
    )
    # Bounded retention: keep eight weeks of delivery receipts, never content snapshots.
    db.execute(
        delete(WeeklyDigest).where(
            WeeklyDigest.created_at < now - timedelta(days=56),
            WeeklyDigest.state.in_(["sent", "skipped", "failed"]),
        ).execution_options(synchronize_session=False)
    )
    db.commit()
    return identifier, state
