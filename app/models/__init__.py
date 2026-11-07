"""Model registry. Import every model here so Alembic sees the full metadata."""

from app.models.community import (
    CommunityMedia,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    ContentReport,
    DiscussionFollow,
    DiscussionReplyRead,
    Follow,
)
from app.models.jobs import Job, JobApplication
from app.models.messages import DirectMessage
from app.models.profile import CredentialClaim, FieldVisibility, NurseProfile
from app.models.recruitment import (
    DiscoverySchedule,
    DiscoveryTask,
    RecruitmentOrganization,
    RecruitmentSource,
    SourceEvent,
)
from app.models.user import User
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.models.verification import EvidenceAccess, EvidenceDocument, VerificationCase

__all__ = [
    "CommunityMedia",
    "CommunityPost",
    "CommunityReply",
    "CommunityTopic",
    "Connection",
    "ContentReport",
    "CredentialClaim",
    "DirectMessage",
    "DiscoverySchedule",
    "DiscoveryTask",
    "DiscussionFollow",
    "DiscussionReplyRead",
    "EvidenceAccess",
    "EvidenceDocument",
    "FieldVisibility",
    "Follow",
    "Job",
    "JobApplication",
    "NurseProfile",
    "RecruitmentOrganization",
    "RecruitmentSource",
    "SourceEvent",
    "User",
    "VacancyEvent",
    "VacancyRecord",
    "VacancySnapshot",
    "VerificationCase",
]
