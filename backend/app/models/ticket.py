from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ProcessingStatus, TicketChannel, TicketPriority

if TYPE_CHECKING:
    from app.models.ai_qa_report import AiQaReport
    from app.models.integration import Integration
    from app.models.manager_feedback import ManagerFeedback
    from app.models.user import User


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "external_ticket_id",
            "ticket_closed_at",
            name="tickets_integration_id_external_ticket_id_ticket_closed_at_key",
        ),
        Index(
            "tickets_assigned_agent_id_ticket_closed_at_idx",
            "assigned_agent_id",
            desc("ticket_closed_at"),
        ),
        Index("tickets_processing_status_idx", "processing_status"),
        Index("tickets_ticket_closed_at_idx", desc("ticket_closed_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integrations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_ticket_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    assigned_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    customer_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    channel: Mapped[TicketChannel] = mapped_column(
        ENUM(TicketChannel, name="TicketChannel", create_type=False),
        default=TicketChannel.EMAIL,
        nullable=False,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        ENUM(TicketPriority, name="TicketPriority", create_type=False),
        default=TicketPriority.NORMAL,
        nullable=False,
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        ENUM(ProcessingStatus, name="ProcessingStatus", create_type=False),
        default=ProcessingStatus.QUEUED,
        nullable=False,
    )
    raw_transcript: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    ticket_metadata: Mapped[Any] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    first_response_time_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    total_resolution_time_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    ticket_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
    )
    ticket_closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    integration: Mapped["Integration"] = relationship(
        "Integration",
        back_populates="tickets",
    )
    assigned_agent: Mapped["User"] = relationship(
        "User",
        back_populates="assigned_tickets",
    )
    ai_qa_report: Mapped[Optional["AiQaReport"]] = relationship(
        "AiQaReport",
        back_populates="ticket",
        uselist=False,
        cascade="all, delete-orphan",
    )
    manager_feedbacks: Mapped[List["ManagerFeedback"]] = relationship(
        "ManagerFeedback",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )

