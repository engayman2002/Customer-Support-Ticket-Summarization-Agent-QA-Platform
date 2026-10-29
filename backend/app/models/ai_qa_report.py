from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import IssueCategory, ResolutionStatus, SentimentTrajectory

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class AiQaReport(Base):
    __tablename__ = "ai_qa_reports"
    __table_args__ = (
        Index("ai_qa_reports_agent_score_idx", "agent_score"),
        Index(
            "ai_qa_reports_is_resolved_properly_premature_closure_detect_idx",
            "is_resolved_properly",
            "premature_closure_detected",
        ),
        Index("ai_qa_reports_issue_category_idx", "issue_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    core_issue: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    issue_category: Mapped[IssueCategory] = mapped_column(
        ENUM(IssueCategory, name="IssueCategory", create_type=False),
        nullable=False,
    )
    resolution_status: Mapped[ResolutionStatus] = mapped_column(
        ENUM(ResolutionStatus, name="ResolutionStatus", create_type=False),
        nullable=False,
    )
    is_resolved_properly: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    premature_closure_detected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    premature_closure_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    agent_score: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    empathy_rating: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    clarity_and_accuracy_rating: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    ownership_and_efficiency_rating: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    customer_sentiment_trajectory: Mapped[SentimentTrajectory] = mapped_column(
        ENUM(SentimentTrajectory, name="SentimentTrajectory", create_type=False),
        nullable=False,
    )
    strengths: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    areas_for_improvement: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    flagged_evidence_quotes: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    actionable_coaching_plan: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    model_used: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    inference_latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )

    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="ai_qa_report",
    )

