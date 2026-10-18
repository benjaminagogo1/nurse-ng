"""Registration and credential checks.

Password hashing lives in ``app.core.security``. This module owns the rules
around account creation and sign-in, not the password primitive.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.validators import E164_RE, normalize_phone
from app.models.user import User, UserStatus

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class AuthError(ValueError):
    """A registration input the user can correct."""


def validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    return password


def register_user(db: Session, *, phone: str, password: str) -> User:
    """Create an active user. Raises ``AuthError`` for invalid input."""
    validate_password(password)

    normalised = normalize_phone(phone)
    if not E164_RE.match(normalised):
        raise AuthError("Enter a phone number in international format, e.g. +2348012345678.")

    existing = db.scalar(select(User.id).where(User.phone == normalised))
    if existing is not None:
        raise AuthError("An account with that phone number already exists.")

    user = User(phone=normalised, hashed_password="")
    user.set_password(password)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # The unique constraint is the authority if two requests race.
        db.rollback()
        raise AuthError("An account with that phone number already exists.") from None

    db.refresh(user)
    return user


def authenticate_user(db: Session, *, phone: str, password: str) -> User | None:
    """Return the user for valid credentials, otherwise None.

    The response deliberately does not distinguish an unknown number from a
    wrong password. Timing still differs slightly; a dummy hash check belongs
    here once login rate limiting exists.
    """
    normalised = normalize_phone(phone)
    user = db.scalar(select(User).where(User.phone == normalised))
    if user is None or not user.hashed_password:
        return None

    try:
        valid = user.check_password(password)
    except Exception:
        # A malformed or unknown stored hash must never authenticate a user.
        return None

    if not valid:
        return None
    if not user.is_active or user.status != UserStatus.ACTIVE:
        return None
    return user
