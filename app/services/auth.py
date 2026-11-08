"""Registration and credential checks.

Password hashing lives in ``app.core.security``. This module owns the rules
around account creation and sign-in, not the password primitive.
"""

import re
from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.core.validators import E164_RE, normalize_phone
from app.models.user import AccountType, User, UserStatus

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A real Argon2 hash checked when no account matches, so an unknown number and
# a wrong password cost roughly the same work (DECISIONS L39). Generated once
# at import rather than stored: it is never compared for authentication.
_DUMMY_PASSWORD_HASH = hash_password("nurse-ng-dummy-password")


class AuthError(ValueError):
    """A registration input the user can correct."""


class LoginLockedError(ValueError):
    """Sign-in refused because repeated failures locked the account."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many unsuccessful sign-in attempts.")
        self.retry_after_seconds = retry_after_seconds


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive timestamps; interpret those as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _verify_dummy_password(password: str) -> None:
    try:
        verify_password(password, _DUMMY_PASSWORD_HASH)
    except Exception:
        # A failed dummy check must still look like a failed sign-in.
        return


def _release_expired_lock(db: Session, user: User) -> None:
    if user.locked_until is None:
        return
    if _as_utc(user.locked_until) <= _utcnow():
        # A completed lock starts a fresh count (DECISIONS L40).
        user.locked_until = None
        user.failed_login_attempts = 0
        db.commit()


def _record_failed_attempt(db: Session, user: User) -> None:
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= settings.login_lockout_threshold:
        user.locked_until = _utcnow() + timedelta(seconds=settings.login_lockout_seconds)
    db.commit()


def _clear_lock_state(db: Session, user: User) -> None:
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


def validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    return password


def register_user(
    db: Session,
    *,
    phone: str,
    password: str,
    full_name: str = "",
    email: str = "",
    account_type: str = AccountType.NURSE.value,
) -> User:
    """Create an active user. Raises ``AuthError`` for invalid input."""
    validate_password(password)
    full_name = full_name.strip()
    email = email.strip()
    if len(full_name) > 120:
        raise AuthError("Your name must be at most 120 characters.")
    if email and (len(email) > 254 or not _EMAIL_RE.fullmatch(email)):
        raise AuthError("Enter a valid email address.")
    if account_type not in {role.value for role in AccountType}:
        raise AuthError("Choose a nurse, employer, or partner account.")

    normalised = normalize_phone(phone)
    if not E164_RE.match(normalised):
        raise AuthError("Enter a phone number in international format, e.g. +2348012345678.")

    existing = db.scalar(select(User.id).where(User.phone == normalised))
    if existing is not None:
        raise AuthError("An account with that phone number already exists.")

    user = User(
        phone=normalised,
        full_name=full_name,
        email=email or None,
        account_type=account_type,
        hashed_password="",
    )
    if user.email and db.scalar(select(User.id).where(User.email == user.email)) is not None:
        raise AuthError("An account with that email address already exists.")
    user.set_password(password)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # The unique constraint is the authority if two requests race.
        db.rollback()
        raise AuthError("An account with that phone number or email already exists.") from None

    db.refresh(user)
    return user


def authenticate_user(db: Session, *, phone: str, password: str) -> User | None:
    """Return the user for valid credentials, otherwise None.

    The response for an unknown number and a wrong password is deliberately
    identical, including the dummy hash check. Raises ``LoginLockedError``
    when repeated failures have locked the account.
    """
    normalised = normalize_phone(phone)
    user = db.scalar(select(User).where(User.phone == normalised))
    if user is None or not user.hashed_password:
        _verify_dummy_password(password)
        return None

    _release_expired_lock(db, user)
    if user.locked_until is not None:
        retry_after = ceil((_as_utc(user.locked_until) - _utcnow()).total_seconds())
        if retry_after > 0:
            raise LoginLockedError(retry_after_seconds=retry_after)
        # The lock expired between the two reads; treat it as released.
        _clear_lock_state(db, user)

    try:
        valid = user.check_password(password)
    except Exception:
        # A malformed or unknown stored hash must never authenticate a user.
        valid = False

    if not valid:
        _record_failed_attempt(db, user)
        return None
    if not user.is_active or user.status != UserStatus.ACTIVE:
        return None

    _clear_lock_state(db, user)
    return user


def save_account_details(db: Session, user: User, *, full_name: str, email: str,
                         current_password: str = "") -> None:
    full_name, email = full_name.strip(), email.strip()
    if not full_name or len(full_name) > 120:
        raise AuthError("Enter your full name (up to 120 characters).")
    if email and (len(email) > 254 or not _EMAIL_RE.fullmatch(email)):
        raise AuthError("Enter a valid email address.")
    current_email = user.email or ""
    if email != current_email:
        from sqlalchemy import delete

        from app.models.account import AccountToken
        from app.services.accounts import verify_current_password

        verify_current_password(db, user, current_password)
        user.email_verified_at = None
        db.execute(delete(AccountToken).where(AccountToken.user_id == user.id))
    user.full_name = full_name
    user.email = email or None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AuthError("An account with that email address already exists.") from None
