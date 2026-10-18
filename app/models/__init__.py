"""Model registry. Import every model here so Alembic sees the full metadata."""

from app.models.profile import CredentialClaim, FieldVisibility, NurseProfile
from app.models.user import User

__all__ = ["CredentialClaim", "FieldVisibility", "NurseProfile", "User"]
