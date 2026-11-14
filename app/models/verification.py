"""Document-review domain: cases, private evidence, and access audit.

The label supported by this domain is **document reviewed**, never source
confirmed. A reviewer inspects an uploaded licence/certificate and a
government-issued identity document and matches the names. Nothing here checks
NMCN's (Nursing and Midwifery Council of Nigeria) records (DECISIONS L47-L52).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.profile import NurseProfile


class CaseStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class EvidenceKind(StrEnum):
    LICENCE = "licence"
    GOVERNMENT_ID = "government_id"
    NURSING_CERTIFICATE = "nursing_certificate"
    ADDITIONAL_CERT = "additional_cert"

class VerificationCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "verification_cases"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nurse_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    # Supplied by the nurse; shown to the reviewer but never published.
    registration_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default=CaseStatus.PENDING)

    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_display_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )

    profile: Mapped["NurseProfile"] = relationship()
    evidence: Mapped[list["EvidenceDocument"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<VerificationCase {self.id} {self.status}>"


class EvidenceDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_documents"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_cases.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20))
    # Original name is for the reviewer's context only; the file on disk uses
    # the opaque ``storage_name``.
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    storage_name: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped["VerificationCase"] = relationship(back_populates="evidence")

    def __repr__(self) -> str:
        return f"<EvidenceDocument {self.kind} {self.storage_name}>"


class EvidenceAccess(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row each time a reviewer opens an evidence file.

    Auditing reads matters as much as auditing decisions: the evidence is the
    most sensitive data the platform holds (DECISIONS L49).
    """

    __tablename__ = "evidence_accesses"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="CASCADE"),
        index=True,
    )
    accessed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    evidence: Mapped["EvidenceDocument"] = relationship()

    def __repr__(self) -> str:
        return f"<EvidenceAccess {self.evidence_id}>"
