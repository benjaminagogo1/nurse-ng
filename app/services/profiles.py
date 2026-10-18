"""Read-side queries for profiles. Every public read goes through here."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import FieldVisibility, NurseProfile, Visibility


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
