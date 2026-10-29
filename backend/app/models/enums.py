import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    AGENT = "AGENT"


class CrmType(str, enum.Enum):
    ZENDESK = "ZENDESK"
    FRESHDESK = "FRESHDESK"
    INTERCOM = "INTERCOM"
    CUSTOM = "CUSTOM"


class TicketChannel(str, enum.Enum):
    EMAIL = "EMAIL"
    LIVE_CHAT = "LIVE_CHAT"
    SOCIAL = "SOCIAL"
    WEB_FORM = "WEB_FORM"
    API = "API"


class TicketPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ProcessingStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    EVALUATED = "EVALUATED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class IssueCategory(str, enum.Enum):
    BILLING = "BILLING"
    TECHNICAL_BUG = "TECHNICAL_BUG"
    ACCOUNT_ACCESS = "ACCOUNT_ACCESS"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    HOW_TO = "HOW_TO"
    CANCELLATION = "CANCELLATION"
    OTHER = "OTHER"


class ResolutionStatus(str, enum.Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    PREMATURELY_CLOSED = "PREMATURELY_CLOSED"
    ESCALATED_PROPERLY = "ESCALATED_PROPERLY"


class SentimentTrajectory(str, enum.Enum):
    IMPROVED = "IMPROVED"
    UNCHANGED_POSITIVE = "UNCHANGED_POSITIVE"
    UNCHANGED_NEGATIVE = "UNCHANGED_NEGATIVE"
    DEGRADED = "DEGRADED"


class FeedbackReadStatus(str, enum.Enum):
    UNREAD = "UNREAD"
    READ = "READ"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CoachingPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

