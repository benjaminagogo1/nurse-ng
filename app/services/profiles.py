"""Profile reads and writes. Every public read goes through here.

Writes are scoped to the signed-in user in the web layer; the service itself
accepts a ``User`` rather than a profile identifier so a caller cannot address
someone else's profile by guessing an identifier.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.profile import (
    FieldVisibility,
    NurseProfile,
    ProfessionalStatus,
    ProfileStatus,
    Visibility,
)
from app.models.user import User

DISPLAY_NAME_MAX = 120
HEADLINE_MAX = 160
LOCATION_MAX = 120
BIO_MAX = 5000

PROFESSIONAL_STATUS_LABELS: dict[str, str] = {
    ProfessionalStatus.STUDENT.value: "Student",
    ProfessionalStatus.GRADUATE.value: "Graduate awaiting licensure",
    ProfessionalStatus.REGISTERED.value: "Registered nurse",
    ProfessionalStatus.SPECIALIST.value: "Specialist nurse",
}

# Fields a nurse can choose to share. Credential claims and evidence are not
# shareable until the verification domain exists.
SHAREABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("display_name", "Display name"),
    ("professional_status", "Professional status"),
    ("headline", "Headline"),
    ("location", "Location"),
    ("bio", "About you"),
)
SHAREABLE_FIELD_NAMES = frozenset(name for name, _ in SHAREABLE_FIELDS)

# The "employers" level is reserved for employer accounts, which do not exist
# yet. Offering an inert option would mislead nurses, so it is rejected.
ALLOWED_VISIBILITIES = frozenset(
    {Visibility.PRIVATE.value, Visibility.PUBLIC.value}
)


class ProfileError(ValueError):
    """A profile input the user can correct."""


def field_visibility(db: Session, profile: NurseProfile, field: str) -> str:
    """Return the visibility for one profile field.

    Absence of a row means private. This is the default that keeps the product
    from leaking fields simply because a form forgot to ask.
    """
    row = db.scalar(
        select(FieldVisibility).where(
            FieldVisibility.profile_id == profile.id,
            FieldVisibility.field == field,
        )
    )
    return row.visibility if row is not None else Visibility.PRIVATE


def public_field_names(db: Session, profile: NurseProfile) -> set[str]:
    rows = db.scalars(
        select(FieldVisibility.field).where(
            FieldVisibility.profile_id == profile.id,
            FieldVisibility.visibility == Visibility.PUBLIC,
        )
    ).all()
    return set(rows)


def get_profile_for_user(db: Session, user_id: UUID) -> NurseProfile | None:
    """Return the profile owned by ``user_id``, if one exists."""
    return db.scalar(select(NurseProfile).where(NurseProfile.user_id == user_id))


def professional_status_label(value: str) -> str:
    """Human-readable label for a stored professional status."""
    return PROFESSIONAL_STATUS_LABELS.get(value, value)


def validate_profile_input(
    *,
    display_name: str,
    headline: str,
    location: str,
    bio: str,
    professional_status: str,
) -> dict[str, str]:
    """Validate and normalise profile fields.

    Lengths mirror the database columns so an over-long value is reported as a
    form error instead of raising a database error.
    """
    status = (professional_status or "").strip()
    if status not in PROFESSIONAL_STATUS_LABELS:
        raise ProfileError("Choose a valid professional status.")

    return {
        "display_name": _clean(
            display_name,
            field="Display name",
            max_length=DISPLAY_NAME_MAX,
            required=True,
        ),
        "headline": _clean(headline, field="Headline", max_length=HEADLINE_MAX),
        "location": _clean(location, field="Location", max_length=LOCATION_MAX),
        "bio": _clean(bio, field="Bio", max_length=BIO_MAX),
        "professional_status": status,
    }


def _clean(
    value: str,
    *,
    field: str,
    max_length: int,
    required: bool = False,
) -> str:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise ProfileError(f"{field} is required.")
    if len(cleaned) > max_length:
        raise ProfileError(f"{field} must be at most {max_length} characters.")
    return cleaned


def save_profile(
    db: Session,
    user: User,
    *,
    display_name: str,
    headline: str,
    location: str,
    bio: str,
    professional_status: str,
) -> NurseProfile:
    """Create or update the signed-in user's profile.

    New profiles start as ``draft`` and non-discoverable. There is no path here
    that makes a profile public; field visibility stays private until a later
    increment adds explicit controls.
    """
    values = validate_profile_input(
        display_name=display_name,
        headline=headline,
        location=location,
        bio=bio,
        professional_status=professional_status,
    )

    profile = get_profile_for_user(db, user.id)
    if profile is None:
        profile = NurseProfile(
            user_id=user.id,
            status=ProfileStatus.DRAFT,
            discoverable=False,
        )
        db.add(profile)

    for field, value in values.items():
        setattr(profile, field, value)

    try:
        db.commit()
    except IntegrityError:
        # The unique constraint on user_id is the authority if two requests race.
        db.rollback()
        raise ProfileError("A profile already exists for this account.") from None

    db.refresh(profile)
    return profile


def get_visibility_map(db: Session, profile: NurseProfile) -> dict[str, str]:
    """Return the visibility of every shareable field.

    A missing row means private; the map always contains every shareable field.
    """
    rows = db.scalars(
        select(FieldVisibility).where(FieldVisibility.profile_id == profile.id)
    ).all()
    stored = {row.field: row.visibility for row in rows}
    return {
        name: stored.get(name, Visibility.PRIVATE.value)
        for name, _ in SHAREABLE_FIELDS
    }


def save_sharing_settings(
    db: Session,
    profile: NurseProfile,
    choices: dict[str, str],
) -> dict[str, str]:
    """Persist field visibility choices.

    Only shareable fields and private/public values are accepted. Private
    choices delete the row, so "no row means private" stays true. Setting a
    field to public creates or updates its row.
    """
    unknown = set(choices) - SHAREABLE_FIELD_NAMES
    if unknown:
        raise ProfileError("Unknown profile field in sharing settings.")

    cleaned: dict[str, str] = {}
    for name, value in choices.items():
        visibility = (value or "").strip()
        if visibility not in ALLOWED_VISIBILITIES:
            raise ProfileError("Choose private or public for every field.")
        cleaned[name] = visibility

    rows = db.scalars(
        select(FieldVisibility).where(FieldVisibility.profile_id == profile.id)
    ).all()
    existing = {row.field: row for row in rows}

    for name, visibility in cleaned.items():
        row = existing.get(name)
        if visibility == Visibility.PRIVATE.value:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(
                FieldVisibility(
                    profile_id=profile.id,
                    field=name,
                    visibility=visibility,
                )
            )
        else:
            row.visibility = visibility

    db.commit()
    return get_visibility_map(db, profile)


def public_profile_fields(db: Session, profile: NurseProfile) -> dict[str, str]:
    """Return only the fields the owner has made public."""
    visibility = get_visibility_map(db, profile)
    fields: dict[str, str] = {}
    for name, _ in SHAREABLE_FIELDS:
        if visibility[name] != Visibility.PUBLIC.value:
            continue
        value = getattr(profile, name)
        if name == "professional_status":
            value = professional_status_label(value)
        if value:
            fields[name] = value
    return fields


def get_active_profile_by_public_id(
    db: Session,
    public_id: UUID,
) -> NurseProfile | None:
    """Return an active profile by its public identifier, or None.

    Inactive profiles and unknown identifiers are indistinguishable to callers.
    """
    return db.scalar(
        select(NurseProfile).where(
            NurseProfile.public_id == public_id,
            NurseProfile.status == ProfileStatus.ACTIVE,
        )
    )


def activate_profile(
    db: Session,
    user: User,
    profile: NurseProfile,
) -> NurseProfile:
    """Make a profile shareable. Activation never makes it discoverable."""
    if profile.user_id != user.id:
        raise ProfileError("This profile does not belong to the signed-in user.")
    if not (profile.display_name or "").strip():
        raise ProfileError("Add a display name before activating your profile.")

    profile.status = ProfileStatus.ACTIVE
    # Invariant: the pilot has no directory, so activation must never opt a
    # profile into discovery, even if the column was changed elsewhere.
    profile.discoverable = False
    db.commit()
    db.refresh(profile)
    return profile


def deactivate_profile(db: Session, profile: NurseProfile) -> NurseProfile:
    """Return an active profile to draft, which turns its share link off."""
    profile.status = ProfileStatus.DRAFT
    db.commit()
    db.refresh(profile)
    return profile
