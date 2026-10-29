from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import CoachingPriority, FeedbackReadStatus

if TYPE_CHECKING:
    from app.models.ticket import Ticket
    from app.models.user import User


class ManagerFeedback(Base):
    __tablename__ = "manager_feedback"
    __table_args__ = (
        Index(
            "manager_feedback_agent_id_read_status_created_at_idx",
            "agent_id",
            "read_status",
            desc("created_at"),
        ),
        Index("manager_feedback_ticket_id_idx", "ticket_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    manager_override_score: Mapped[Optional[int]] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    coaching_priority: Mapped[CoachingPriority] = mapped_column(
        ENUM(CoachingPriority, name="CoachingPriority", create_type=False),
        default=CoachingPriority.MEDIUM,
        nullable=False,
    )
    comments: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    action_items: Mapped[Any] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    read_status: Mapped[FeedbackReadStatus] = mapped_column(
        ENUM(FeedbackReadStatus, name="FeedbackReadStatus", create_type=False),
        default=FeedbackReadStatus.UNREAD,
        nullable=False,
    )
    agent_acknowledgement_note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
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

    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="manager_feedbacks",
    )
    manager: Mapped["User"] = relationship(
        "User",
        foreign_keys=[manager_id],
        back_populates="authored_feedbacks",
    )
    agent: Mapped["User"] = relationship(
        "User",
        foreign_keys=[agent_id],
        back_populates="received_feedbacks",
    )

