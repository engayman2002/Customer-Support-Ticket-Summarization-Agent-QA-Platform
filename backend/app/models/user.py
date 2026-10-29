from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.manager_feedback import ManagerFeedback
    from app.models.ticket import Ticket


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("users_role_is_active_idx", "role", "is_active"),
        Index("users_manager_id_idx", "manager_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        ENUM(UserRole, name="UserRole", create_type=False),
        default=UserRole.AGENT,
        nullable=False,
    )
    external_crm_agent_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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

    manager: Mapped[Optional["User"]] = relationship(
        "User",
        remote_side="User.id",
        back_populates="direct_reports",
    )
    direct_reports: Mapped[List["User"]] = relationship(
        "User",
        back_populates="manager",
    )
    assigned_tickets: Mapped[List["Ticket"]] = relationship(
        "Ticket",
        back_populates="assigned_agent",
    )
    authored_feedbacks: Mapped[List["ManagerFeedback"]] = relationship(
        "ManagerFeedback",
        foreign_keys="ManagerFeedback.manager_id",
        back_populates="manager",
    )
    received_feedbacks: Mapped[List["ManagerFeedback"]] = relationship(
        "ManagerFeedback",
        foreign_keys="ManagerFeedback.agent_id",
        back_populates="agent",
    )

