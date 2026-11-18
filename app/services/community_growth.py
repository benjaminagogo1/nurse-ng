"""Public communities, learning participation and useful-answer recognition."""

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import (
    CommunityAnswer,
    CommunityMembership,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    ContentStatus,
    HelpfulReply,
)
from app.models.user import User, UserStatus
from app.services.community import (
    CommunityError,
    _clean_community_name,
    _clean_text,
    _lock_community_name,
    _topic_slug,
    get_published_post,
)
from app.services.member_interests import INTEREST_OPTIONS, interest_values

POST_KINDS = {
    "question": "Question",
    "discussion": "Conversation",
    "experience": "Experience",
    "activity": "Learning activity",
}
ACTIVITY_FORMATS = {
    "discussion": "Case discussion",
    "practice": "Practice challenge",
    "q-and-a": "Peer Q&A",
}

# Editable starting points only; choosing one never creates a community.
COMMUNITY_EXAMPLES = {
    "critical-care": {
        "name": "Emergency & Critical Care",
        "description": (
            "For nurses interested in emergency and critical care to discuss practice, "
            "share resources and learn from one another."
        ),
        "welcome_text": (
            "Welcome nurses at every career stage. Introduce yourself and share a question "
            "or resource that could help the group."
        ),
        "rules": (
            "Be respectful. Protect patient privacy and avoid identifying case details. "
            "Share sources for clinical information and follow your workplace guidance."
        ),
        "interest": "Critical care",
    },
    "new-nurse": {
        "name": "New Nurse Support Circle",
        "description": (
            "For new nurses and supportive colleagues to share first-job experiences, "
            "ask questions and find encouragement during the transition into practice."
        ),
        "welcome_text": (
            "Starting out can bring plenty of questions. Share a challenge, a small win "
            "or advice you wish you had received."
        ),
        "rules": (
            "Welcome questions without judgement. Be kind, protect patient and colleague "
            "privacy, and share opportunities with clear sources."
        ),
        "interest": "",
    },
    "local-network": {
        "name": "Nurses in Abuja",
        "description": (
            "For nurses in Abuja to connect locally, exchange professional opportunities "
            "and share useful events and resources. Change the location to suit your network."
        ),
        "welcome_text": (
            "Introduce yourself and tell us what you would like to find or share "
            "with local colleagues."
        ),
        "rules": (
            "Respect colleagues and their privacy. Check opportunity details before sharing, "
            "include sources, and ask permission before posting personal contact information."
        ),
        "interest": "",
    },
    "exam-circle": {
        "name": "Exam Preparation Circle",
        "description": (
            "For nurses preparing for a shared exam to discuss study plans, practise questions "
            "and encourage one another. Add your exam name to make the purpose clear."
        ),
        "welcome_text": (
            "Tell us which exam you are preparing for and one topic you would like "
            "to practise together."
        ),
        "rules": (
            "Explain your reasoning and share reliable study sources. Respect copyright, "
            "exam rules and one another's learning pace."
        ),
        "interest": "",
    },
    "school-network": {
        "name": "School & Alumni Network",
        "description": (
            "For nursing students, alumni and mentors from a shared school to exchange advice, "
            "resources and opportunities. Add your school's name to help colleagues find you."
        ),
        "welcome_text": (
            "Welcome students, alumni and mentors. Introduce yourself and share what you "
            "hope to learn or contribute."
        ),
        "rules": (
            "Be welcoming across year groups. Protect personal and patient information. "
            "Check announcements and opportunities before sharing them."
        ),
        "interest": "",
    },
    "research": {
        "name": "Nursing Research Exchange",
        "description": (
            "For nurses interested in research methods, evidence and collaboration to discuss "
            "projects, ask questions and share useful resources."
        ),
        "welcome_text": (
            "Share a research interest, a methods question or a resource that could help "
            "another member."
        ),
        "rules": (
            "Credit sources and collaborators. Protect participant privacy, respect research "
            "approvals and do not share confidential or unpublished data without permission."
        ),
        "interest": "Research",
    },
}


def suggested_communities(db: Session, user: User, *, limit: int = 4):
    from app.services.profiles import get_profile_for_user

    profile = get_profile_for_user(db, user.id)
    interests = interest_values(profile.interests) if profile else []
    joined = select(CommunityMembership.topic_id).where(CommunityMembership.user_id == user.id)
    statement = select(CommunityTopic).where(
        CommunityTopic.is_active.is_(True), CommunityTopic.id.not_in(joined)
    )
    return list(
        db.scalars(
            statement.order_by(
                case((CommunityTopic.interest.in_(interests), 0), else_=1),
                CommunityTopic.name,
                CommunityTopic.id,
            ).limit(limit)
        )
    )


def activity_time(value: datetime) -> str:
    from app.services.time_display import display_datetime

    current = value if value.tzinfo else value.replace(tzinfo=UTC)
    return display_datetime(current.astimezone(ZoneInfo("Africa/Lagos")))


def _active(user: User) -> None:
    if not user.is_active or user.status != UserStatus.ACTIVE:
        raise CommunityError("Sign in with an active account to participate.")


def _insert(db: Session):
    return sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert


def _community_values(name, description, welcome_text, rules, interest):
    clean_name, _ = _clean_community_name(name)
    interest = (interest or "").strip()
    if interest and interest not in INTEREST_OPTIONS:
        raise CommunityError("Choose an interest from the available options.")
    return {
        "name": clean_name,
        "description": _clean_text(description, field="Description", maximum=500, required=True),
        "welcome_text": _clean_text(welcome_text, field="Welcome message", maximum=1000),
        "rules": _clean_text(rules, field="Community guidelines", maximum=2000, required=True),
        "interest": interest,
    }


def can_manage_community(user: User | None, topic: CommunityTopic) -> bool:
    return bool(
        user
        and user.is_active
        and user.status == UserStatus.ACTIVE
        and (user.is_staff or topic.created_by_user_id == user.id)
    )


def create_community(db: Session, user: User, **values) -> CommunityTopic:
    _active(user)
    cleaned = _community_values(**values)
    topic = CommunityTopic(
        **cleaned, slug=_topic_slug(cleaned["name"]), created_by_user_id=user.id, is_active=True
    )
    try:
        _lock_community_name(db, user)
        db.add(topic)
        db.flush()
        db.add(CommunityMembership(user_id=user.id, topic_id=topic.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CommunityError("A community with that name already exists.") from None
    db.refresh(topic)
    return topic


def update_community(db: Session, user: User, topic: CommunityTopic, **values) -> None:
    if not can_manage_community(user, topic):
        raise CommunityError("Only the community host or staff can edit this community.")
    cleaned = _community_values(**values)
    # Existing links stay valid when a host edits the community name.
    for key, value in cleaned.items():
        setattr(topic, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CommunityError("A community with that name already exists.") from None


def membership(db: Session, user: User, topic: CommunityTopic, *, joined: bool) -> None:
    _active(user)
    current = db.scalar(
        select(CommunityTopic)
        .where(CommunityTopic.id == topic.id, CommunityTopic.is_active.is_(True))
        .with_for_update()
    )
    if current is None:
        raise CommunityError("This community is no longer available.")
    if joined:
        db.execute(
            _insert(db)(CommunityMembership)
            .values(user_id=user.id, topic_id=topic.id)
            .on_conflict_do_nothing(index_elements=["user_id", "topic_id"])
        )
    else:
        db.execute(
            delete(CommunityMembership).where(
                CommunityMembership.user_id == user.id, CommunityMembership.topic_id == topic.id
            )
        )
    db.commit()


def community_summaries(db: Session, topics, user: User | None) -> dict:
    result = {topic.id: {"members": 0, "joined": False} for topic in topics}
    if not result:
        return result
    for topic_id, count in db.execute(
        select(CommunityMembership.topic_id, func.count())
        .join(User, User.id == CommunityMembership.user_id)
        .where(
            CommunityMembership.topic_id.in_(result),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
        .group_by(CommunityMembership.topic_id)
    ):
        result[topic_id]["members"] = count
    if user:
        for topic_id in db.scalars(
            select(CommunityMembership.topic_id).where(
                CommunityMembership.user_id == user.id, CommunityMembership.topic_id.in_(result)
            )
        ):
            result[topic_id]["joined"] = True
    return result


def communities(db: Session, *, query="", interest="", user=None, mine=False, page=1):
    statement = select(CommunityTopic).where(CommunityTopic.is_active.is_(True))
    for word in query.strip().split():
        statement = statement.where(
            or_(
                CommunityTopic.name.icontains(word, autoescape=True),
                CommunityTopic.description.icontains(word, autoescape=True),
            )
        )
    if interest:
        statement = statement.where(CommunityTopic.interest == interest)
    if mine:
        if user is None:
            return []
        statement = statement.join(CommunityMembership).where(
            CommunityMembership.user_id == user.id
        )
    return list(
        db.scalars(
            statement.order_by(CommunityTopic.name, CommunityTopic.id)
            .offset((page - 1) * 20)
            .limit(21)
        )
    )


def post_details(
    *, post_kind="discussion", title="", activity_format="", activity_starts_at=""
) -> dict:
    if post_kind not in POST_KINDS:
        raise CommunityError("Choose a valid conversation type.")
    clean_title = _clean_text(title, field="Title", maximum=160, required=post_kind == "activity")
    starts = None
    if post_kind == "activity":
        if activity_format not in ACTIVITY_FORMATS:
            raise CommunityError("Choose a learning activity format.")
        if activity_starts_at:
            try:
                raw = str(activity_starts_at)
                if len(raw) > 40 or "T" not in raw:
                    raise ValueError
                starts = datetime.fromisoformat(raw)
                if starts.tzinfo is None:
                    starts = starts.replace(tzinfo=ZoneInfo("Africa/Lagos"))
                starts = starts.astimezone(UTC)
            except (ValueError, OverflowError):
                raise CommunityError("Enter a valid activity date and time.") from None
    else:
        activity_format = ""
    return {
        "post_kind": post_kind,
        "title": clean_title,
        "activity_format": activity_format,
        "activity_starts_at": starts,
    }


def answer_summaries(db: Session, posts) -> dict:
    result = {post.id: {"answered": False, "answer_id": None} for post in posts}
    if not result:
        return result
    for post_id, reply_id in db.execute(
        select(CommunityAnswer.post_id, CommunityAnswer.reply_id)
        .join(CommunityReply, CommunityReply.id == CommunityAnswer.reply_id)
        .where(
            CommunityAnswer.post_id.in_(result),
            CommunityReply.post_id == CommunityAnswer.post_id,
            CommunityReply.status == ContentStatus.PUBLISHED,
        )
    ):
        result[post_id] = {"answered": True, "answer_id": reply_id}
    return result


def helpful_summaries(db: Session, replies, user: User | None) -> dict:
    result = {reply.id: {"count": 0, "marked": False} for reply in replies}
    if not result:
        return result
    for reply_id, count in db.execute(
        select(HelpfulReply.reply_id, func.count())
        .join(User, User.id == HelpfulReply.user_id)
        .where(
            HelpfulReply.reply_id.in_(result),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
        .group_by(HelpfulReply.reply_id)
    ):
        result[reply_id]["count"] = count
    if user:
        for reply_id in db.scalars(
            select(HelpfulReply.reply_id).where(
                HelpfulReply.user_id == user.id, HelpfulReply.reply_id.in_(result)
            )
        ):
            result[reply_id]["marked"] = True
    return result


def _public_reply(db: Session, reply_id: UUID) -> tuple[CommunityReply, CommunityPost]:
    reply = db.scalar(
        select(CommunityReply)
        .where(CommunityReply.id == reply_id, CommunityReply.status == ContentStatus.PUBLISHED)
        .with_for_update()
    )
    post = get_published_post(db, reply.post_id) if reply else None
    if reply is None or post is None:
        raise CommunityError("This response is no longer available.")
    return reply, post


def recognize_reply(db: Session, user: User, reply_id: UUID, *, marked: bool) -> CommunityReply:
    _active(user)
    reply, _ = _public_reply(db, reply_id)
    if reply.author_id == user.id:
        raise CommunityError("Helpful recognition is for another member's response.")
    if marked:
        db.execute(
            _insert(db)(HelpfulReply)
            .values(user_id=user.id, reply_id=reply.id)
            .on_conflict_do_nothing(index_elements=["user_id", "reply_id"])
        )
    else:
        db.execute(
            delete(HelpfulReply).where(
                HelpfulReply.user_id == user.id, HelpfulReply.reply_id == reply.id
            )
        )
    db.commit()
    return reply


def select_answer(db: Session, user: User, reply_id: UUID, *, selected: bool) -> CommunityReply:
    _active(user)
    reply, post = _public_reply(db, reply_id)
    if post.post_kind != "question" or post.author_id != user.id:
        raise CommunityError("Only the question's author can choose its answer.")
    if selected:
        db.execute(
            _insert(db)(CommunityAnswer)
            .values(post_id=post.id, reply_id=reply.id)
            .on_conflict_do_update(
                index_elements=["post_id"],
                set_={"reply_id": reply.id, "selected_at": datetime.now(UTC)},
            )
        )
    else:
        db.execute(
            delete(CommunityAnswer).where(
                CommunityAnswer.post_id == post.id, CommunityAnswer.reply_id == reply.id
            )
        )
    db.commit()
    return reply
