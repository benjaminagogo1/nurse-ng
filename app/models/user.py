"""Identity domain: the custom user model.

Phone is the primary contact and the login identifier. Email is optional and
unique when present. Roles are not a column; group membership and permissions
arrive with the authorization layer.
"""

from enum import StrEnum

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.security import hash_password, verify_password
from app.core.validators import E164_RE, normalize_phone
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)

    @validates("phone")
    def _normalise_phone(self, key: str, value: str) -> str:  # noqa: ARG002
        normalised = normalize_phone(value or "")
        if not E164_RE.match(normalised):
            raise ValueError(
                "Enter a phone number in international format, e.g. +2348012345678."
            )
        return normalised

    @validates("email")
    def _normalise_email(self, key: str, value: str | None) -> str | None:  # noqa: ARG002
        if not value:
            return None
        local, _, domain = value.partition("@")
        return f"{local}@{domain.lower()}" if domain else value

    def set_password(self, password: str) -> None:
        self.hashed_password = hash_password(password)

    def check_password(self, password: str) -> bool:
        return verify_password(password, self.hashed_password)

    def __repr__(self) -> str:
        return f"<User {self.phone}>"
