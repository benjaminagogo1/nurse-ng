"""Revocable personal invitations and aggregate, owner-only adoption counts.

Personal invitations are signed, expiring and revocable. Attribution applies
to a valid new-account signup journey; existing sign-ins are not new referrals.
Owners see aggregates, never referred members' private activity histories.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.public_urls import public_site_ready, public_url
from app.models.activity import UserDailyActivity
from app.models.community import CommunityPost, CommunityReply, CommunityTopic, ContentStatus
from app.models.participation import MemberReferral, ReferralInvitation, ReferralVisit
from app.models.user import User, UserStatus
from app.services.community import CommunityError, _clean_text
from app.services.community_growth import _active, _insert
from app.services.community_sharing import community_destination


def signer():
    return URLSafeSerializer(settings.secret_key, salt="nurse-ng-personal-invitation-v1")


def invitation_link(item):
    return public_url("/invite/" + signer().dumps(str(item.id))) if public_site_ready() else ""


def create_invitation(db, user, *, destination, label="", now=None):
    """Save an active member's expiring personal link to a valid public destination."""
    _active(user)
    if not public_site_ready():
        raise CommunityError("Invitations will be available when the community is online.")
    destination = community_destination(db, destination)
    if not destination:
        raise CommunityError("Choose an available public community or conversation.")
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    now = now or datetime.now(UTC)
    count = (
        db.scalar(
            select(func.count())
            .select_from(ReferralInvitation)
            .where(
                ReferralInvitation.owner_id == user.id,
                ReferralInvitation.created_at >= now - timedelta(days=1),
            )
        )
        or 0
    )
    if count >= 20:
        raise CommunityError("You have created twenty invitations today. Share an existing one.")
    item = ReferralInvitation(
        owner_id=user.id,
        destination=destination,
        label=_clean_text(label, field="Invitation label", maximum=160),
        expires_at=now + timedelta(days=90),
    )
    db.add(item)
    db.commit()
    return item


def resolve(db, token, *, now=None):
    """Verify the invitation signature, lifetime, owner and current destination availability."""
    if not isinstance(token, str) or len(token) > 256:
        return None
    try:
        identifier = UUID(signer().loads(token))
    except (BadSignature, ValueError, TypeError):
        return None
    item = db.scalar(
        select(ReferralInvitation)
        .join(User, User.id == ReferralInvitation.owner_id)
        .where(
            ReferralInvitation.id == identifier,
            ReferralInvitation.revoked_at.is_(None),
            ReferralInvitation.expires_at > (now or datetime.now(UTC)),
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
        )
    )
    return item if item and community_destination(db, item.destination) else None


def record_visit(db, request, item, token):
    # Session randomness identifies browsers without IP addresses or fingerprinting.
    """Persist an approximate browser receipt without collecting IP/fingerprint identity."""
    seed = request.session.setdefault("referral_browser", secrets.token_urlsafe(24))
    browser_hash = hmac.new(settings.secret_key.encode(), seed.encode(), hashlib.sha256).hexdigest()
    db.execute(
        _insert(db)(ReferralVisit)
        .values(invitation_id=item.id, browser_hash=browser_hash)
        .on_conflict_do_nothing()
    )
    if not request.session.get("user_id"):
        # Keep the first valid invitation during this browser's signup journey.
        if not resolve(db, request.session.get("pending_referral", "")):
            request.session["pending_referral"] = token
    db.commit()


def attribute_signup(db, request, user):
    """Only call while creating a new account; existing sign-ins never count."""
    item = resolve(db, request.session.get("pending_referral", ""))
    if item and item.owner_id != user.id:
        db.execute(
            _insert(db)(MemberReferral)
            .values(user_id=user.id, inviter_id=item.owner_id, invitation_id=item.id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )


def revoke(db, user, identifier):
    """Let the invitation owner stop future use of the personal link."""
    item = db.get(ReferralInvitation, identifier)
    if not item or item.owner_id != user.id:
        raise CommunityError("This invitation is unavailable.")
    item.revoked_at = datetime.now(UTC)
    db.commit()


def summaries(db, user, *, page=1):
    """Return only owner-visible aggregate invitation outcomes, not referred identities."""
    items = list(
        db.scalars(
            select(ReferralInvitation)
            .where(ReferralInvitation.owner_id == user.id)
            .order_by(ReferralInvitation.created_at.desc(), ReferralInvitation.id)
            .offset((page - 1) * 20)
            .limit(21)
        )
    )
    result = []
    now = datetime.now(UTC)
    for item in items:
        referrals = select(MemberReferral.user_id).join(User, User.id == MemberReferral.user_id)
        referrals = referrals.where(
            MemberReferral.invitation_id == item.id,
            User.is_active.is_(True),
            User.status == UserStatus.ACTIVE,
            User.is_staff.is_(False),
        )
        post_exists = (
            select(CommunityPost.id)
            .join(CommunityTopic)
            .where(
                CommunityPost.author_id == MemberReferral.user_id,
                CommunityPost.status == ContentStatus.PUBLISHED,
                CommunityTopic.is_active.is_(True),
            )
            .correlate(MemberReferral)
            .exists()
        )
        reply_exists = (
            select(CommunityReply.id)
            .join(CommunityPost)
            .join(CommunityTopic)
            .where(
                CommunityReply.author_id == MemberReferral.user_id,
                CommunityReply.status == ContentStatus.PUBLISHED,
                CommunityPost.status == ContentStatus.PUBLISHED,
                CommunityTopic.is_active.is_(True),
            )
            .correlate(MemberReferral)
            .exists()
        )
        # A return means activity on a later Nigerian calendar day, not background polling.
        if db.get_bind().dialect.name == "sqlite":
            return_day = func.date(MemberReferral.created_at, "+1 hours")
        else:
            from sqlalchemy import Date, cast

            return_day = cast(func.timezone("Africa/Lagos", MemberReferral.created_at), Date)
        return_exists = (
            select(UserDailyActivity.user_id)
            .where(
                UserDailyActivity.user_id == MemberReferral.user_id,
                UserDailyActivity.activity_date > return_day,
            )
            .correlate(MemberReferral)
            .exists()
        )

        def total(query):
            return db.scalar(select(func.count()).select_from(query.subquery())) or 0

        expires = item.expires_at if item.expires_at.tzinfo else item.expires_at.replace(tzinfo=UTC)
        result.append(
            {
                "invitation": item,
                "link": invitation_link(item),
                "available": not item.revoked_at
                and expires > now
                and bool(community_destination(db, item.destination)),
                "visits": db.scalar(
                    select(func.count())
                    .select_from(ReferralVisit)
                    .where(ReferralVisit.invitation_id == item.id)
                )
                or 0,
                "signups": total(referrals),
                "contributors": total(referrals.where(or_(post_exists, reply_exists))),
                "returning": total(referrals.where(return_exists)),
            }
        )
    return result
