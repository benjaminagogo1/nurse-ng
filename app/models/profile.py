"""Nurse profiles, credential claims, and field-level visibility.

Visibility defaults to private. A field is visible only when an explicit
``FieldVisibility`` row raises it. Discoverability is opt-in and defaults to
false; nothing here makes a profile public.

``CredentialClaim.status`` is a projection of the verification domain. A claim
must never reach ``document_reviewed``, ``source_confirmed``, or ``revoked``
without a corresponding verification decision row (build plan, section 5).
The document-review workflow (DECISIONS L47-L52) records its outcome on
``document_reviewed_at`` and does not write credential claims; a claim may only
be raised by a future source-confirmed decision.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.uuid import uuid7
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class Visibility(StrEnum):
    """Explicit field-sharing levels; a missing FieldVisibility row stays private."""
    PRIVATE = "private"
    EMPLOYERS = "employers"
    PUBLIC = "public"


class ProfessionalStatus(StrEnum):
    """Member-declared nursing career-stage vocabulary, not verification evidence."""
    STUDENT = "student"
    GRADUATE = "graduate"
    REGISTERED = "registered"
    SPECIALIST = "specialist"


class ProfileStatus(StrEnum):
    """Private professional-profile lifecycle, independent of account active status."""
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ClaimType(StrEnum):
    """Supported kinds of professional credential claims."""
    REGISTRATION = "registration"
    LICENCE = "licence"
    QUALIFICATION = "qualification"
    SPECIALTY = "specialty"
    EMPLOYMENT = "employment"


class ClaimStatus(StrEnum):
    """Credential trust vocabulary; stronger claims require corresponding verification decisions."""
    SELF_DECLARED = "self_declared"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    DOCUMENT_REVIEWED = "document_reviewed"
    SOURCE_CONFIRMED = "source_confirmed"
    EXPIRED = "expired"
    DISPUTED = "disputed"
    UNABLE_TO_VERIFY = "unable_to_verify"
    REVOKED = "revoked"


class NurseProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Owner-managed professional record; public reads must apply field visibility and opt-in
    rules.
    """
    __tablename__ = "nurse_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    # Public identifier. Never the licence or registration number.
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        unique=True,
        default=uuid7,
    )

    professional_status: Mapped[str] = mapped_column(
        String(20), default=ProfessionalStatus.STUDENT
    )
    status: Mapped[str] = mapped_column(String(20), default=ProfileStatus.DRAFT)
    discoverable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    display_name: Mapped[str] = mapped_column(String(120), default="")
    headline: Mapped[str] = mapped_column(String(160), default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    bio: Mapped[str] = mapped_column(Text, default="")

    # Set only when a reviewer approves a document-review case. Null means no
    # approved review; the label is "document reviewed", never "verified"
    # (DECISIONS L47). The case table remains the audit record.
    document_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Snapshot of the display name that was matched during the latest approved
    # review. It can differ from the current self-declared display name (L63).
    document_reviewed_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )

    user: Mapped[User] = relationship()
    claims: Mapped[list["CredentialClaim"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    field_visibilities: Mapped[list["FieldVisibility"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )

    qualification: Mapped[str] = mapped_column(String(120), default="", server_default="")
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skills: Mapped[str] = mapped_column(String(600), default="", server_default="")
    interests: Mapped[str] = mapped_column(String(600), default="", server_default="")

    def __repr__(self) -> str:
        return f"<NurseProfile {self.public_id}>"


class CredentialClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Professional assertion with verification state; document review alone is not source
    confirmation.
    """
    __tablename__ = "credential_claims"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nurse_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    type: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(255))
    issuer: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(20), default=ClaimStatus.SELF_DECLARED)
    visibility: Mapped[str] = mapped_column(String(20), default=Visibility.PRIVATE)

    profile: Mapped["NurseProfile"] = relationship(back_populates="claims")

    __table_args__ = (
        Index("claim_profile_status_idx", "profile_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<CredentialClaim {self.type} {self.status}>"


class FieldVisibility(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Explicit sharing level for one named field of one profile."""
    __tablename__ = "field_visibilities"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nurse_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    field: Mapped[str] = mapped_column(String(32))
    visibility: Mapped[str] = mapped_column(String(20), default=Visibility.PRIVATE)

    profile: Mapped["NurseProfile"] = relationship(back_populates="field_visibilities")

    __table_args__ = (
        UniqueConstraint("profile_id", "field", name="uniq_profile_field_visibility"),
    )

    def __repr__(self) -> str:
        return f"<FieldVisibility {self.field}: {self.visibility}>"
