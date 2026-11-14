"""Staff-reviewed organizations and individually authorized employer accounts."""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class EmployerOrganization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employer_organizations"

    name: Mapped[str] = mapped_column(String(160))
    name_key: Mapped[str] = mapped_column(String(320), unique=True)
    website: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")


class EmployerMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employer_memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employer_organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    authority_details: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    organization: Mapped[EmployerOrganization] = relationship()
    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_employer_member"),)


class EmployerReviewEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employer_review_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employer_organizations.id", ondelete="CASCADE"), index=True
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employer_memberships.id", ondelete="SET NULL")
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text)
