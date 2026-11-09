"""Transactional activity notifications with live permission checks."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.community import (
    CommunityPost,
    CommunityReply,
    Connection,
    ConnectionStatus,
    ContentStatus,
    DiscussionFollow,
)
from app.models.jobs import Job, JobApplication
from app.models.messages import DirectMessage
from app.models.notifications import Notification, NotificationPreference
from app.models.user import User, UserStatus

CATEGORIES = {
    "replies": ("Conversations", "Replies to your posts, responses and followed discussions."),
    "connections": ("Connections", "New connection requests and accepted invitations."),
    "messages": ("Messages", "New private messages from your connections."),
    "opportunities": (
        "Opportunities",
        "New matches and deadline reminders for saved opportunities.",
    ),
    "applications": ("Applications", "New applications and changes to application status."),
}
PAGE_SIZE = 20


def preferences(db: Session, user: User) -> dict:
    rows = {
        p.category: p
        for p in db.scalars(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
            )
        )
    }
    return {
        key: {
            "in_app": rows[key].in_app if key in rows else True,
            "email": rows[key].email if key in rows else False,
        }
        for key in CATEGORIES
    }


def save_preferences(db: Session, user: User, values: dict) -> None:
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    for category in CATEGORIES:
        value = values[category]
        statement = insert(NotificationPreference).values(
            user_id=user.id,
            category=category,
            in_app=value["in_app"],
            email=value["email"],
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "category"],
                set_={
                    "in_app": value["in_app"],
                    "email": value["email"],
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        if not value["email"]:
            db.execute(
                update(Notification)
                .where(
                    Notification.recipient_id == user.id,
                    Notification.category == category,
                    Notification.email_state.in_(["queued", "sending", "failed"]),
                )
                .values(
                    email_state="skipped",
                    email_to="",
                    email_lease_until=None,
                    email_lease_token=None,
                )
            )
    db.commit()


def emit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    recipients,
    category: str,
    kind: str,
    event_key: str,
    **targets,
) -> None:
    """Append notices inside the caller's transaction; never commit or send here."""
    ids = set(recipients) - {actor_id, None}
    if not ids:
        return
    accounts = db.scalars(
        select(User).where(
            User.id.in_(ids),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    ).all()
    choices = {
        p.user_id: p
        for p in db.scalars(
            select(NotificationPreference).where(
                NotificationPreference.user_id.in_(ids),
                NotificationPreference.category == category,
            )
        )
    }
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    timestamp = datetime.now(UTC)
    rows = []
    for account in accounts:
        choice = choices.get(account.id)
        in_app = choice.in_app if choice else True
        email = bool(choice and choice.email and account.email and account.email_verified_at)
        if not in_app and not email and category != "opportunities":
            continue
        rows.append(
            dict(
                recipient_id=account.id,
                actor_id=actor_id,
                category=category,
                kind=kind,
                event_key=event_key,
                in_app=in_app,
                email_to=account.email if email else "",
                email_state="queued" if email else "skipped",
                email_next_attempt=timestamp if email else None,
                created_at=timestamp,
                **targets,
            )
        )
    # Keep large discussion fan-outs within SQLite/PostgreSQL parameter limits.
    for start in range(0, len(rows), 100):
        db.execute(
            insert(Notification)
            .values(rows[start : start + 100])
            .on_conflict_do_nothing(
                index_elements=["recipient_id", "event_key"],
            )
        )


def notify_reply(db: Session, reply: CommunityReply, post: CommunityPost) -> None:
    recipients = set(
        db.scalars(
            select(DiscussionFollow.user_id).where(
                DiscussionFollow.post_id == post.id,
            )
        )
    ) | {post.author_id}
    if reply.in_reply_to_id:
        parent = db.get(CommunityReply, reply.in_reply_to_id)
        if parent:
            recipients.add(parent.author_id)
    emit(
        db,
        actor_id=reply.author_id,
        recipients=recipients,
        category="replies",
        kind="reply",
        event_key=f"reply:{reply.id}",
        reply_id=reply.id,
        post_id=post.id,
    )


def notify_connection(db: Session, connection: Connection, *, accepted: bool = False) -> None:
    actor = connection.recipient_user_id if accepted else connection.requester_user_id
    recipient = connection.requester_user_id if accepted else connection.recipient_user_id
    if not accepted:
        # A re-sent invitation is a new event; old declined invitations must not reappear.
        db.execute(delete(Notification).where(Notification.connection_id == connection.id))
    emit(
        db,
        actor_id=actor,
        recipients={recipient},
        category="connections",
        kind="connection_accepted" if accepted else "connection_request",
        event_key=f"connection:{connection.id}:{uuid.uuid4().hex}",
        connection_id=connection.id,
    )


def visible_condition():
    """Recheck the source and relationship whenever listing, counting or emailing."""
    actor_active = (
        select(User.id)
        .where(
            User.id == Notification.actor_id,
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
        .exists()
    )
    parent = aliased(CommunityReply)
    reply_access = (
        select(CommunityReply.id)
        .join(
            CommunityPost,
            CommunityPost.id == CommunityReply.post_id,
        )
        .where(
            CommunityReply.id == Notification.reply_id,
            CommunityReply.status == ContentStatus.PUBLISHED,
            CommunityPost.status == ContentStatus.PUBLISHED,
            or_(
                CommunityPost.author_id == Notification.recipient_id,
                select(DiscussionFollow.id)
                .where(
                    DiscussionFollow.post_id == CommunityPost.id,
                    DiscussionFollow.user_id == Notification.recipient_id,
                )
                .correlate(CommunityPost, Notification)
                .exists(),
                select(parent.id)
                .where(
                    parent.id == CommunityReply.in_reply_to_id,
                    parent.author_id == Notification.recipient_id,
                    parent.status == ContentStatus.PUBLISHED,
                )
                .correlate(CommunityReply, Notification)
                .exists(),
            ),
        )
        .correlate(Notification)
        .exists()
    )
    connection_access = (
        select(Connection.id)
        .where(
            Connection.id == Notification.connection_id,
            or_(
                Connection.requester_user_id == Notification.recipient_id,
                Connection.recipient_user_id == Notification.recipient_id,
            ),
            Connection.status.in_([ConnectionStatus.PENDING, ConnectionStatus.ACCEPTED]),
        )
        .exists()
    )
    connected = (
        select(Connection.id)
        .where(
            Connection.status == ConnectionStatus.ACCEPTED,
            or_(
                and_(
                    Connection.requester_user_id == Notification.recipient_id,
                    Connection.recipient_user_id == Notification.actor_id,
                ),
                and_(
                    Connection.recipient_user_id == Notification.recipient_id,
                    Connection.requester_user_id == Notification.actor_id,
                ),
            ),
        )
        .exists()
    )
    message_access = (
        select(DirectMessage.id)
        .where(
            DirectMessage.id == Notification.message_id,
            DirectMessage.recipient_id == Notification.recipient_id,
        )
        .exists()
        & connected
    )
    application_access = (
        select(JobApplication.id)
        .join(Job)
        .where(
            JobApplication.id == Notification.application_id,
            or_(
                JobApplication.applicant_user_id == Notification.recipient_id,
                Job.employer_user_id == Notification.recipient_id,
            ),
        )
        .exists()
    )
    from app.services.opportunity_watch import job_notice_access

    return or_(
        and_(
            Notification.category == "opportunities",
            Notification.actor_id.is_(None),
            job_notice_access(),
        ),
        and_(
            actor_active,
            or_(
                and_(Notification.category == "replies", reply_access),
                and_(Notification.category == "connections", connection_access),
                and_(Notification.category == "messages", message_access),
                and_(Notification.category == "applications", application_access),
            ),
        ),
    )


def inbox_query(user: User):
    return select(Notification).where(
        Notification.recipient_id == user.id,
        Notification.in_app.is_(True),
        visible_condition(),
    )


def unread_count(db: Session, user: User) -> int:
    return (
        db.scalar(
            inbox_query(user)
            .where(Notification.read_at.is_(None))
            .with_only_columns(
                func.count(),
                maintain_column_froms=True,
            )
        )
        or 0
    )


def inbox_page(db: Session, user: User, *, category="", unread=False, before=None):
    query = inbox_query(user)
    if category:
        query = query.where(Notification.category == category)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    if before:
        cursor = db.scalar(inbox_query(user).where(Notification.id == before))
        if cursor:
            query = query.where(
                or_(
                    Notification.created_at < cursor.created_at,
                    and_(
                        Notification.created_at == cursor.created_at,
                        Notification.id < cursor.id,
                    ),
                )
            )
        else:
            return [], None
    rows = list(
        db.scalars(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .options(selectinload(Notification.actor))
            .limit(PAGE_SIZE + 1)
        )
    )
    return rows[:PAGE_SIZE], str(rows[PAGE_SIZE - 1].id) if len(rows) > PAGE_SIZE else None


def get_notice(db: Session, user: User, identifier: uuid.UUID) -> Notification | None:
    return db.scalar(inbox_query(user).where(Notification.id == identifier))


def mark_read(db: Session, user: User, ids) -> None:
    db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.id.in_(ids),
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    db.commit()


def card(db: Session, notice: Notification) -> dict:
    """Render from current authorised sources; do not retain private message snapshots."""
    name = (notice.actor.community_name if notice.actor else "") or "A member"
    heading, description, path = "New activity", "", "/notifications"
    icon = {
        "replies": "chat",
        "connections": "users",
        "messages": "mail",
        "applications": "briefcase",
        "opportunities": "briefcase",
    }[notice.category]
    if notice.category == "opportunities":
        job = db.get(Job, notice.job_id)
        heading = (
            "A saved opportunity closes soon"
            if notice.kind == "deadline_reminder"
            else "A new opportunity matches your interests"
        )
        description = job.title + " · " + job.organization
        path = f"/jobs/{job.id}"
    elif notice.category == "replies":
        post = db.get(CommunityPost, notice.post_id)
        heading = f"{name} replied to a conversation"
        description = (post.body or "A community conversation")[:160]
        path = f"/posts/{notice.post_id}/replies/{notice.reply_id}"
    elif notice.category == "connections":
        heading = f"{name} " + (
            "accepted your connection request"
            if notice.kind == "connection_accepted"
            else "sent you a connection request"
        )
        description = "Keep growing your professional network."
        path = "/network"
    elif notice.category == "messages":
        heading = f"{name} sent you a message"
        description = "Open your conversation to read it."
        path = f"/messages/{notice.actor_id}"
    elif notice.category == "applications":
        application = db.get(JobApplication, notice.application_id)
        heading = (
            "New application received"
            if notice.kind == "application_received"
            else (
                "Application withdrawn"
                if notice.application_status == "withdrawn"
                else "Your application has an update"
            )
        )
        description = application.job.title
        if notice.application_status:
            description += " · " + notice.application_status.replace("_", " ").capitalize()
        path = f"/applications/{notice.application_id}"
    return {
        "notice": notice,
        "heading": heading,
        "description": description,
        "path": path,
        "icon": icon,
    }
