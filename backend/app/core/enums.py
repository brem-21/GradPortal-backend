from enum import StrEnum


class UserRole(StrEnum):
    STUDENT = "student"
    MENTOR = "mentor"
    ADMIN = "admin"


class OpportunityType(StrEnum):
    GRADUATE_PROGRAM = "graduate_program"
    SCHOLARSHIP = "scholarship"
    FELLOWSHIP = "fellowship"
    ASSISTANTSHIP = "assistantship"
    RESEARCH_POSITION = "research_position"
    INTERNSHIP = "internship"
    JOB = "job"


class FieldOfStudy(StrEnum):
    COMPUTER_SCIENCE = "computer_science"
    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"
    DATA_SCIENCE = "data_science"
    DATA_ENGINEERING = "data_engineering"
    DATA_ANALYTICS = "data_analytics"


class DegreeLevel(StrEnum):
    MASTERS = "masters"
    PHD = "phd"
    POSTDOC = "postdoc"
    CERTIFICATE = "certificate"


class FundingType(StrEnum):
    FULLY_FUNDED = "fully_funded"
    PARTIAL = "partial"
    TUITION_WAIVER = "tuition_waiver"
    STIPEND_ONLY = "stipend_only"
    UNFUNDED = "unfunded"
    UNKNOWN = "unknown"


class SourceKind(StrEnum):
    UNIVERSITY = "university"
    SCHOLARSHIP_PORTAL = "scholarship_portal"
    JOB_BOARD = "job_board"
    LINKEDIN = "linkedin"
    HANDSHAKE = "handshake"
    MANUAL = "manual"


class OpportunityStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApplicationStatus(StrEnum):
    SAVED = "saved"
    IN_PROGRESS = "in_progress"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class OutreachStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class NotificationType(StrEnum):
    NEW_MATCH = "new_match"
    DEADLINE_REMINDER = "deadline_reminder"
    OPPORTUNITY_APPROVED = "opportunity_approved"
    OPPORTUNITY_SUBMITTED = "opportunity_submitted"
    MENTORSHIP_REQUEST = "mentorship_request"
    MENTORSHIP_ACCEPTED = "mentorship_accepted"
    MENTORSHIP_DECLINED = "mentorship_declined"
    OUTREACH_SENT = "outreach_sent"
    OUTREACH_FAILED = "outreach_failed"


class MentorshipStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    COMPLETED = "completed"


class DigestFrequency(StrEnum):
    INSTANT = "instant"
    DAILY = "daily"
    WEEKLY = "weekly"
    OFF = "off"
