"""Organization approval never follows from public role selection or a matching name.

Membership, organization approval and active account state are checked together
at use time. Selecting an employer account type never grants organization access
or access to another employer's applications.
"""

from urllib.parse import urlsplit

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.models.employers import EmployerMembership, EmployerOrganization, EmployerReviewEvent
from app.models.user import AccountType, User, UserStatus


class EmployerError(ValueError):
    pass


def authorization_condition(user_id, organization_id):
    """Reusable SQL gate, including suspension and contact verification revocation."""
    member, org, user = aliased(EmployerMembership), aliased(EmployerOrganization), aliased(User)
    return exists(select(member.id).join(org, member.organization_id == org.id)
                  .join(user, member.user_id == user.id).where(
        member.user_id == user_id, member.organization_id == organization_id,
        member.status == "approved", org.status == "approved",
        user.account_type == AccountType.EMPLOYER,
        user.is_active.is_(True), user.status == UserStatus.ACTIVE,
        user.email.is_not(None), user.email_verified_at.is_not(None),
    ).correlate_except(member, org, user))


def authorized(db, user_id, organization_id):
    return bool(organization_id and db.scalar(select(
        authorization_condition(user_id, organization_id)
    )))


def memberships(db, user):
    return list(db.scalars(select(EmployerMembership).where(
        EmployerMembership.user_id == user.id
    ).order_by(EmployerMembership.created_at.desc())))


def approved_organizations(db, user):
    return list(db.scalars(select(EmployerOrganization).where(
        authorization_condition(user.id, EmployerOrganization.id)
    ).order_by(EmployerOrganization.name)))


def request_membership(db, user, *, name, website, authority_details):
    if user.account_type != AccountType.EMPLOYER or not user.is_active:
        raise EmployerError("Only employer accounts can request organization approval.")
    name = " ".join(name.split())
    website, details = website.strip(), authority_details.strip()
    if not name or len(name) > 160:
        raise EmployerError("Enter an organization name of at most 160 characters.")
    try:
        parsed = urlsplit(website)
        valid = parsed.scheme == "https" and parsed.hostname and not parsed.username
    except ValueError:
        valid = False
    if not valid or len(website) > 500:
        raise EmployerError("Enter the organization's official HTTPS website.")
    if not details or len(details) > 2000:
        raise EmployerError("Explain your authority to recruit in at most 2,000 characters.")
    org = db.scalar(select(EmployerOrganization).where(
        EmployerOrganization.name_key == name.casefold()
    ))
    try:
        if org is None:
            org = EmployerOrganization(name=name, name_key=name.casefold(), website=website)
            db.add(org)
            db.flush()
        existing = db.scalar(select(EmployerMembership).where(
            EmployerMembership.user_id == user.id, EmployerMembership.organization_id == org.id
        ))
        if existing:
            raise EmployerError("You already have a request for this organization.")
        member = EmployerMembership(
            organization_id=org.id, user_id=user.id,
            authority_details=f"Submitted website: {website}\n\n{details}",
        )
        db.add(member)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EmployerError("A request already exists. Refresh the page to see it.") from None
    return member


def review_membership(db, reviewer, member, *, action, note, identity_checked=False,
                      authority_checked=False, include_legacy=False):
    if not reviewer.is_staff or not reviewer.is_active or reviewer.status != UserStatus.ACTIVE:
        raise EmployerError("Staff access required.")
    if member.user_id == reviewer.id:
        raise EmployerError("A reviewer cannot approve or change their own membership.")
    if action not in {"approve", "reject", "revoke", "suspend_organization"}:
        raise EmployerError("Choose a valid review action.")
    note = note.strip()
    if not note or len(note) > 2000:
        raise EmployerError("Record the checks and decision in at most 2,000 characters.")
    if action == "approve":
        if not identity_checked or not authority_checked:
            raise EmployerError("Confirm both organization identity and recruiting authority.")
        user = member.user
        if (user.account_type != AccountType.EMPLOYER or not user.is_active
                or user.status != UserStatus.ACTIVE
                or not user.email_verified_at or not user.email):
            raise EmployerError("The employer needs an active account and a verified email.")
        member.organization.status = "approved"
        member.status = "approved"
        if include_legacy:
            from app.models.jobs import Job

            # Staff explicitly confirms the old listings too. Names alone never grant access.
            db.execute(update(Job).where(
                Job.employer_user_id == member.user_id,
                Job.employer_organization_id.is_(None),
                Job.source_id.is_(None), Job.organization == member.organization.name,
            ).values(employer_organization_id=member.organization_id))
            note += "\nStaff also confirmed this account's matching legacy listings."
    elif action == "suspend_organization":
        member.organization.status = "suspended"
    else:
        member.status = "rejected" if action == "reject" else "revoked"
    db.add(EmployerReviewEvent(
        organization_id=member.organization_id, membership_id=member.id,
        reviewer_id=reviewer.id, action=action, note=note,
    ))
    db.commit()
