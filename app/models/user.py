"""Identity domain: the custom user model.

Phone is the primary contact and the login identifier. Email is optional and
unique when present. Roles are not a column; group membership and permissions
arrive with the authorization layer.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.security import hash_password, verify_password
from app.core.validators import E164_RE, normalize_phone
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class AccountType(StrEnum):
    NURSE = "nurse"
    EMPLOYER = "employer"
    PARTNER = "partner"

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
    account_type: Mapped[str] = mapped_column(
        String(20), default=AccountType.NURSE, server_default="nurse", index=True
    )

    # Public identity used on community contributions. It is deliberately
    # separate from a nurse profile so posting never exposes a private profile.
    community_name: Mapped[str] = mapped_column(
        String(80), default="", server_default=""
    )
    community_name_key: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    community_name_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    community_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    community_upload_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    community_upload_window_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )

    # Login lockout state (DECISIONS L38). Persisted so a restart cannot clear
    # an active lock and so every worker sees the same counter.
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "community_name_key",
            name="uniq_users_community_name_key",
        ),
        CheckConstraint(
            "community_storage_bytes >= 0 AND community_upload_window_bytes >= 0",
            name="community_byte_counters_nonnegative",
        ),
    )

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
