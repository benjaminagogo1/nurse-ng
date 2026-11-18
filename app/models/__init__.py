"""Model registry. Import every model here so Alembic sees the full metadata."""

from app.models.account import AccountToken, FileDeletion
from app.models.activity import UserDailyActivity
from app.models.community import (
    CommunityAnswer,
    CommunityMedia,
    CommunityMembership,
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    ContentReport,
    DiscussionFollow,
    DiscussionReplyRead,
    Follow,
    HelpfulReply,
)
from app.models.employers import EmployerMembership, EmployerOrganization, EmployerReviewEvent
from app.models.engagement import PostLike
from app.models.events import CommunityEvent, EventAttendance
from app.models.jobs import Job, JobApplication
from app.models.messages import DirectMessage, MessageAttachment, MessageUploadUsage
from app.models.notifications import Notification, NotificationPreference
from app.models.offline import OfflineOperation
from app.models.offline_upload import OfflineUpload
from app.models.opportunities import OpportunityPreference, SavedOpportunity
from app.models.participation import (
    ActivityAttendance,
    ActivityOccurrence,
    ActivitySeries,
    CommunityIntroduction,
    DigestPreference,
    MemberJourney,
    MemberReferral,
    MentorOffer,
    MentorReport,
    Mentorship,
    ReferralInvitation,
    ReferralVisit,
    WeeklyDigest,
)
from app.models.profile import CredentialClaim, FieldVisibility, NurseProfile
from app.models.recruitment import (
    DiscoverySchedule,
    DiscoveryTask,
    RecruitmentOrganization,
    RecruitmentSource,
    SourceEvent,
)
from app.models.reels import Reel, ReelSave
from app.models.social_auth import SocialAuthAttempt, SocialEnrollment, SocialIdentity
from app.models.staff import StaffRoleEvent
from app.models.tour import UserTour
from app.models.user import User
from app.models.vacancies import VacancyEvent, VacancyRecord, VacancySnapshot
from app.models.verification import EvidenceAccess, EvidenceDocument, VerificationCase
from app.models.workers import WorkerHeartbeat

__all__ = [
    "ActivityAttendance", "ActivityOccurrence", "ActivitySeries", "CommunityIntroduction",
    "DigestPreference", "MemberJourney", "MemberReferral", "MentorOffer", "MentorReport",
    "Mentorship", "ReferralInvitation", "ReferralVisit", "WeeklyDigest",
    "CommunityAnswer",
    "CommunityMembership",
    "HelpfulReply",
    "PostLike",
    "StaffRoleEvent",
    "EmployerMembership",
    "EmployerOrganization",
    "EmployerReviewEvent",
    "OfflineOperation",
    "OfflineUpload",
    "CommunityEvent",
    "EventAttendance",
    "SocialAuthAttempt",
    "SocialEnrollment",
    "SocialIdentity",
    "AccountToken",
    "FileDeletion",
    "CommunityMedia",
    "CommunityPost",
    "CommunityReply",
    "CommunityTopic",
    "Connection",
    "ContentReport",
    "CredentialClaim",
    "DirectMessage",
    "MessageAttachment",
    "MessageUploadUsage",
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
    "Notification",
    "NotificationPreference",
    "OpportunityPreference",
    "SavedOpportunity",
    "RecruitmentOrganization",
    "RecruitmentSource",
    "Reel",
    "ReelSave",
    "SourceEvent",
    "User",
    "UserDailyActivity",
    "UserTour",
    "VacancyEvent",
    "VacancyRecord",
    "VacancySnapshot",
    "VerificationCase",
    "WorkerHeartbeat",
]
