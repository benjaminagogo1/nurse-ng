"""Model registry. Import every model here so Alembic sees the full metadata."""

from app.models.community import (
    CommunityMedia,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    ContentReport,
    Follow,
)
from app.models.profile import CredentialClaim, FieldVisibility, NurseProfile
from app.models.user import User
from app.models.verification import EvidenceAccess, EvidenceDocument, VerificationCase

__all__ = [
    "CommunityMedia",
    "CommunityPost",
    "CommunityReply",
    "CommunityTopic",
    "Connection",
    "ContentReport",
    "CredentialClaim",
    "EvidenceAccess",
    "EvidenceDocument",
    "FieldVisibility",
    "Follow",
    "NurseProfile",
    "User",
    "VerificationCase",
]
