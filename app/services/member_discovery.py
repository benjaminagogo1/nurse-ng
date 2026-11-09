"""Explainable suggestions using the viewer's choices and other members' public fields."""

from datetime import UTC, datetime

from sqlalchemy import and_, case, literal, or_, select
from sqlalchemy.orm import joinedload

from app.models.community import Connection, Follow
from app.models.jobs import Job
from app.models.profile import NurseProfile
from app.services.jobs import job_card, list_open_jobs, open_job_condition
from app.services.member_interests import INTEREST_TERMS, clean_interests, interest_values
from app.services.profiles import (
    ProfileError,
    discoverable_condition,
    get_profile_for_user,
    public_field_condition,
    public_profile_fields,
)


def finish_onboarding(db, user, *, interests: str, location: str):
    """Save only the two chosen fields; never publish or change visibility/alerts."""
    try:
        interests = clean_interests(interests)
    except ValueError as exc:
        raise ProfileError(str(exc)) from None
    location = location.strip()
    if len(location) > 120:
        raise ProfileError("Location must be at most 120 characters.")
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        profile = NurseProfile(user_id=user.id, display_name=user.full_name)
        db.add(profile)
    profile.interests = interests
    profile.location = location
    user.onboarding_completed_at = datetime.now(UTC)
    db.commit()


def suggested_people(db, user, *, limit=3):
    own = get_profile_for_user(db, user.id)
    interests = interest_values(own.interests) if own else []
    location = own.location.strip() if own else ""
    score = literal(0)
    for interest in interests:
        score = score + case(
            (
                and_(
                    public_field_condition("interests"),
                    NurseProfile.interests.contains(interest, autoescape=True),
                ),
                2,
            ),
            else_=0,
        )
    if location:
        score = score + case(
            (
                and_(
                    public_field_condition("location"),
                    NurseProfile.location.icontains(location, autoescape=True),
                ),
                1,
            ),
            else_=0,
        )
    following = (
        select(Follow.id)
        .where(
            Follow.follower_user_id == user.id,
            Follow.followed_user_id == NurseProfile.user_id,
        )
        .exists()
    )
    connected = (
        select(Connection.id)
        .where(
            Connection.status.in_(["pending", "accepted"]),
            or_(
                and_(
                    Connection.requester_user_id == user.id,
                    Connection.recipient_user_id == NurseProfile.user_id,
                ),
                and_(
                    Connection.recipient_user_id == user.id,
                    Connection.requester_user_id == NurseProfile.user_id,
                ),
            ),
        )
        .exists()
    )
    profiles = db.scalars(
        select(NurseProfile)
        .where(
            discoverable_condition(),
            NurseProfile.user_id != user.id,
            ~following,
            ~connected,
        )
        .options(joinedload(NurseProfile.user))
        .order_by(
            score.desc(),
            NurseProfile.display_name,
            NurseProfile.id,
        )
        .limit(limit)
    ).all()
    cards = []
    for profile in profiles:
        fields = public_profile_fields(db, profile)
        shared = [i for i in interests if i in interest_values(fields.get("interests", ""))]
        reason = (
            "Shared interest: " + shared[0]
            if shared
            else (
                "Near your chosen location"
                if location and location.casefold() in fields.get("location", "").casefold()
                else "Explore this public profile"
            )
        )
        cards.append({"profile": profile, "fields": fields, "reason": reason})
    return cards


def suggested_opportunities(db, user, *, limit=3):
    profile = get_profile_for_user(db, user.id)
    interests = interest_values(profile.interests) if profile else []
    location = profile.location.strip() if profile else ""
    score = literal(0)
    for interest in interests:
        terms = INTEREST_TERMS.get(interest, ())
        matches = [
            column.icontains(term, autoescape=True)
            for term in terms
            for column in (Job.title, Job.description)
        ]
        if interest == "Fellowships":
            matches.append(Job.job_type == "fellowship")
        elif interest == "Internships":
            matches.append(Job.job_type.in_(["internship", "graduate_programme"]))
        if matches:
            score = score + case((or_(*matches), 2), else_=0)
    if location:
        score = score + case((Job.location.icontains(location, autoescape=True), 1), else_=0)
    jobs = (
        list(
            db.scalars(
                select(Job)
                .where(open_job_condition(), score > 0)
                .order_by(
                    case((Job.country_code == "NG", 0), else_=1),
                    score.desc(),
                    Job.posted_at.desc(),
                    Job.id.desc(),
                )
                .limit(limit)
            ).all()
        )
        if interests or location
        else []
    )
    personalised = bool(jobs)
    if not jobs:
        jobs = list_open_jobs(db, limit=limit)
    return [job_card(job) for job in jobs], personalised
