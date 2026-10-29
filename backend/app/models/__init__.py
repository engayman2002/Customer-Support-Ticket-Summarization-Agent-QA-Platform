"""SQLAlchemy 2.0 ORM Models and PostgreSQL Enums (1:1 parity with Prisma)."""

from app.db.session import Base
from app.models.ai_qa_report import AiQaReport
from app.models.enums import (
    CoachingPriority,
    CrmType,
    FeedbackReadStatus,
    IssueCategory,
    ProcessingStatus,
    ResolutionStatus,
    SentimentTrajectory,
    TicketChannel,
    TicketPriority,
    UserRole,
)
from app.models.integration import Integration
from app.models.manager_feedback import ManagerFeedback
from app.models.ticket import Ticket
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Integration",
    "Ticket",
    "AiQaReport",
    "ManagerFeedback",
    "UserRole",
    "CrmType",
    "TicketChannel",
    "TicketPriority",
    "ProcessingStatus",
    "IssueCategory",
    "ResolutionStatus",
    "SentimentTrajectory",
    "FeedbackReadStatus",
    "CoachingPriority",
]

