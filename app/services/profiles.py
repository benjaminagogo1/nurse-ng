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
QUALIFICATION_MAX = 120
YEARS_EXPERIENCE_MAX = 60
SKILLS_MAX_ITEMS = 12
SKILL_MAX_LENGTH = 40

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
    ("qualification", "Highest qualification"),
    ("years_experience", "Years of experience"),
    ("skills", "Skills"),
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


def _clean_years(value: object) -> int | None:
    cleaned = str(value if value is not None else "").strip()
    if not cleaned:
        return None
    if not cleaned.isdigit():
        raise ProfileError("Years of experience must be a whole number.")
    years = int(cleaned)
    if years > YEARS_EXPERIENCE_MAX:
        raise ProfileError(
            f"Years of experience must be at most {YEARS_EXPERIENCE_MAX}."
        )
    return years


def _clean_skills(value: str) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for raw in (value or "").split(","):
        skill = " ".join(raw.split())
        if not skill:
            continue
        if len(skill) > SKILL_MAX_LENGTH:
            raise ProfileError(
                f"Each skill must be at most {SKILL_MAX_LENGTH} characters."
            )
        key = skill.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(skill)
    if len(items) > SKILLS_MAX_ITEMS:
        raise ProfileError(f"Add at most {SKILLS_MAX_ITEMS} skills.")
    return ", ".join(items)


def validate_profile_input(
    *,
    display_name: str,
    headline: str,
    location: str,
    bio: str,
    professional_status: str,
    qualification: str = "",
    years_experience: str = "",
    skills: str = "",
) -> dict[str, object]:
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
        "qualification": _clean(
            qualification, field="Qualification", max_length=QUALIFICATION_MAX
        ),
        "years_experience": _clean_years(years_experience),
        "skills": _clean_skills(skills),
    }

def save_profile(
    db: Session,
    user: User,
    *,
    display_name: str,
    headline: str,
    location: str,
    bio: str,
    professional_status: str,
    qualification: str = "",
    years_experience: str = "",
    skills: str = "",
) -> NurseProfile:
    """Create or update the signed-in user's profile (always private by default)."""
    values = validate_profile_input(
        display_name=display_name,
        headline=headline,
        location=location,
        bio=bio,
        professional_status=professional_status,
        qualification=qualification,
        years_experience=years_experience,
        skills=skills,
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

    if (
        profile.status == ProfileStatus.ACTIVE
        and profile.discoverable
        and cleaned.get("display_name") == Visibility.PRIVATE.value
    ):
        raise ProfileError(
            "Make the profile private before making its display name private."
        )

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
        if value is None or value == "":
            continue
        fields[name] = str(value)
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
    """Publish a profile after its owner has made the name public."""
    if profile.user_id != user.id:
        raise ProfileError("This profile does not belong to the signed-in user.")
    if not (profile.display_name or "").strip():
        raise ProfileError("Add a display name before activating your profile.")
    if field_visibility(db, profile, "display_name") != Visibility.PUBLIC:
        raise ProfileError(
            "Make your display name public in sharing controls before publishing."
        )

    profile.status = ProfileStatus.ACTIVE
    profile.discoverable = True
    db.commit()
    db.refresh(profile)
    return profile


def deactivate_profile(db: Session, profile: NurseProfile) -> NurseProfile:
    """Return a public profile to private draft state."""
    profile.status = ProfileStatus.DRAFT
    profile.discoverable = False
    db.commit()
    db.refresh(profile)
    return profile


def list_discoverable_profiles(db: Session, *, limit: int = 100) -> list[NurseProfile]:
    """List only profiles whose owners explicitly published them."""
    return list(
        db.scalars(
            select(NurseProfile)
            .where(
                NurseProfile.status == ProfileStatus.ACTIVE,
                NurseProfile.discoverable.is_(True),
            )
            .order_by(NurseProfile.display_name, NurseProfile.created_at)
            .limit(limit)
        ).all()
    )
