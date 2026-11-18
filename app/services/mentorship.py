"""Voluntary peer support with private requests and explicit mutual consent."""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.models.community import Connection, ConnectionStatus
from app.models.notifications import Notification
from app.models.participation import MentorOffer, MentorReport, Mentorship
from app.models.user import User, UserStatus
from app.services.community import CommunityError, _clean_text, connection_pair_key
from app.services.community_growth import _active
from app.services.notifications import emit

TOPICS = {
    "school": "Starting nursing school",
    "study": "Study and examinations",
    "practice": "Clinical practice and transition",
    "career": "Career development",
    "leadership": "Leadership and specialist practice",
    "research": "Research and postgraduate study",
    "teaching": "Teaching and nursing education",
}


def active_account(identifier):
    return (
        select(User.id)
        .where(User.id == identifier, User.is_active.is_(True), User.status == UserStatus.ACTIVE)
        .exists()
    )


def save_offer(
    db,
    user,
    *,
    topics,
    introduction,
    availability,
    capacity=3,
    accepting=False,
    show_completed=False,
):
    _active(user)
    if not user.community_name:
        raise CommunityError("Choose your public display name in Community settings first.")
    selected = sorted(set(topics))
    if not selected or any(topic not in TOPICS for topic in selected):
        raise CommunityError("Choose at least one support topic.")
    if not 1 <= capacity <= 8:
        raise CommunityError("Choose capacity between one and eight colleagues.")
    offer = db.scalar(select(MentorOffer).where(MentorOffer.user_id == user.id).with_for_update())
    active = (
        db.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.mentor_id == user.id, Mentorship.status == "accepted")
        )
        or 0
    )
    if capacity < active:
        raise CommunityError("Capacity cannot be lower than your current accepted requests.")
    values = dict(
        topics=",".join(selected),
        introduction=_clean_text(introduction, field="Introduction", maximum=700, required=True),
        availability=_clean_text(availability, field="Availability", maximum=200, required=True),
        capacity=capacity,
        accepting=accepting,
        show_completed=show_completed,
    )
    if offer is None:
        offer = MentorOffer(user_id=user.id, **values)
        db.add(offer)
    else:
        for key, value in values.items():
            setattr(offer, key, value)
    db.commit()
    return offer


def directory(db, *, topic="", query="", page=1):
    statement = (
        select(MentorOffer, User)
        .join(User, User.id == MentorOffer.user_id)
        .where(
            MentorOffer.accepting.is_(True),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    )
    if topic:
        if topic not in TOPICS:
            raise CommunityError("Choose a support topic from the list.")
        # Topic names are validated keys, separated by commas.
        statement = statement.where(
            ("," + MentorOffer.topics + ",").contains("," + topic + ",", autoescape=True)
        )
    for word in query.split():
        statement = statement.where(
            or_(
                User.community_name.icontains(word, autoescape=True),
                MentorOffer.introduction.icontains(word, autoescape=True),
            )
        )
    rows = db.execute(
        statement.order_by(MentorOffer.created_at.desc(), User.id).offset((page - 1) * 20).limit(21)
    ).all()
    return [offer_card(db, offer, account) for offer, account in rows]


def offer_card(db, offer, account):
    active = (
        db.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.mentor_id == account.id, Mentorship.status == "accepted")
        )
        or 0
    )
    completed = (
        db.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.mentor_id == account.id, Mentorship.status == "completed")
        )
        or 0
    )
    return {
        "offer": offer,
        "name": account.community_name or "Community member",
        "topics": [TOPICS[key] for key in offer.topics.split(",") if key in TOPICS],
        "places": max(0, offer.capacity - active),
        "completed": completed if offer.show_completed else None,
    }


def request_support(db, user, mentor_id, *, topic, goal):
    _active(user)
    if mentor_id == user.id:
        raise CommunityError("Choose another colleague for support.")
    goal = _clean_text(goal, field="Your goal", maximum=1200, required=True)
    offer = db.scalar(
        select(MentorOffer)
        .where(
            MentorOffer.user_id == mentor_id,
            MentorOffer.accepting.is_(True),
            active_account(MentorOffer.user_id),
        )
        .with_for_update()
    )
    if offer is None or topic not in offer.topics.split(","):
        raise CommunityError("This colleague is not accepting requests for that topic.")
    pair = connection_pair_key(user.id, mentor_id)
    existing = db.scalar(select(Mentorship).where(Mentorship.open_pair == pair))
    if existing:
        return existing
    count = (
        db.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(Mentorship.requester_id == user.id, Mentorship.status == "pending")
        )
        or 0
    )
    if count >= 5:
        raise CommunityError("You already have five pending requests. Review those first.")
    count = (
        db.scalar(
            select(func.count())
            .select_from(Mentorship)
            .where(
                Mentorship.mentor_id == mentor_id, Mentorship.status.in_(["pending", "accepted"])
            )
        )
        or 0
    )
    if count >= offer.capacity + 10:
        raise CommunityError("This colleague's request queue is full. Try another colleague.")
    item = Mentorship(
        requester_id=user.id, mentor_id=mentor_id, topic=topic, goal=goal, open_pair=pair
    )
    db.add(item)
    try:
        db.flush()
        emit(
            db,
            actor_id=user.id,
            recipients={mentor_id},
            category="mentorship",
            kind="support_pending",
            event_key=f"support:{item.id}:pending",
            mentorship_id=item.id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        item = db.scalar(select(Mentorship).where(Mentorship.open_pair == pair))
        if item is None:
            raise CommunityError("The request could not be saved. Please try again.") from None
    return item


def owned_request(db, user, identifier, *, staff=False):
    item = db.get(Mentorship, identifier)
    if item is None or (
        user.id not in {item.requester_id, item.mentor_id} and not (staff and user.is_staff)
    ):
        raise CommunityError("This support request is unavailable.")
    return item


def respond(db, user, identifier, action):
    _active(user)
    item = owned_request(db, user, identifier)
    old = item.status
    allowed = (
        (old == "pending" and user.id == item.mentor_id and action in {"accept", "decline"})
        or (old == "pending" and user.id == item.requester_id and action == "withdraw")
        or (old == "accepted" and action in {"complete", "end"})
    )
    if not allowed:
        raise CommunityError("This action is unavailable for the current request.")
    if not db.scalar(
        select(User.id).where(
            User.id == (item.mentor_id if user.id == item.requester_id else item.requester_id),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    ):
        raise CommunityError("The other account is no longer available.")
    now = datetime.now(UTC)
    statuses = {
        "accept": "accepted",
        "decline": "declined",
        "withdraw": "withdrawn",
        "complete": "completed",
        "end": "ended",
    }
    values = {"status": statuses[action], "responded_at": now}
    if action == "accept":
        offer = db.scalar(
            select(MentorOffer).where(MentorOffer.user_id == user.id).with_for_update()
        )
        count = (
            db.scalar(
                select(func.count())
                .select_from(Mentorship)
                .where(Mentorship.mentor_id == user.id, Mentorship.status == "accepted")
            )
            or 0
        )
        if not offer or count >= offer.capacity:
            raise CommunityError("Your support capacity is full. Update your offer first.")
        pair = connection_pair_key(item.requester_id, item.mentor_id)
        connection = db.scalar(select(Connection).where(Connection.pair_key == pair))
        if connection is None:
            connection = Connection(
                requester_user_id=item.requester_id, recipient_user_id=item.mentor_id, pair_key=pair
            )
            db.add(connection)
            db.flush()
        connection.status = ConnectionStatus.ACCEPTED
        connection.responded_at = now
        values["connection_id"] = connection.id
    else:
        values["open_pair"] = None
        if action == "complete":
            values["completed_at"] = now
    changed = db.execute(
        update(Mentorship)
        .where(Mentorship.id == item.id, Mentorship.status == old)
        .values(**values)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise CommunityError("This request changed. Refresh before trying again.")
    other = item.requester_id if user.id == item.mentor_id else item.mentor_id
    emit(
        db,
        actor_id=user.id,
        recipients={other},
        category="mentorship",
        kind="support_" + statuses[action],
        event_key=f"support:{item.id}:{statuses[action]}",
        mentorship_id=item.id,
    )
    db.execute(
        update(Notification)
        .where(Notification.mentorship_id == item.id, Notification.recipient_id == user.id)
        .values(read_at=now)
    )
    db.commit()
    db.refresh(item)
    return item


def requests(db, user, *, page=1):
    return list(
        db.scalars(
            select(Mentorship)
            .where(or_(Mentorship.requester_id == user.id, Mentorship.mentor_id == user.id))
            .order_by(Mentorship.created_at.desc(), Mentorship.id)
            .offset((page - 1) * 20)
            .limit(21)
        )
    )


def report(db, user, identifier, *, reason, details):
    item = owned_request(db, user, identifier)
    if reason not in {"harassment", "privacy", "misinformation", "spam", "other"}:
        raise CommunityError("Choose a report reason.")
    details = _clean_text(details, field="Details", maximum=1000, required=reason == "other")
    key = f"{item.id.hex}:{user.id.hex}"
    existing = db.scalar(select(MentorReport).where(MentorReport.open_key == key))
    if existing:
        return existing
    result = MentorReport(
        request_id=item.id, reporter_id=user.id, reason=reason, details=details, open_key=key
    )
    db.add(result)
    db.commit()
    return result


def review_report(db, staff, identifier, action):
    _active(staff)
    if not staff.is_staff or action not in {"resolve", "dismiss", "pause"}:
        raise CommunityError("Staff access and a valid review action are required.")
    if action == "pause":
        report = db.get(MentorReport, identifier)
        request = db.get(Mentorship, report.request_id) if report else None
        if request:
            db.execute(
                update(MentorOffer)
                .where(MentorOffer.user_id == request.mentor_id)
                .values(accepting=False)
            )
    changed = db.execute(
        update(MentorReport)
        .where(MentorReport.id == identifier, MentorReport.status == "open")
        .values(
            status="dismissed" if action == "dismiss" else "resolved",
            open_key=None,
            reviewed_by_id=staff.id,
            reviewed_at=datetime.now(UTC),
        )
    )
    if changed.rowcount != 1:
        db.rollback()
        raise CommunityError("This report has already been reviewed.")
    db.commit()
