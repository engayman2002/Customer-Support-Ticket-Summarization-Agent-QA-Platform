from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import CrmType

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (
        Index("integrations_crm_type_is_active_idx", "crm_type", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    crm_type: Mapped[CrmType] = mapped_column(
        ENUM(CrmType, name="CrmType", create_type=False),
        nullable=False,
    )
    subdomain_or_base_url: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    encrypted_api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    encrypted_webhook_secret: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    config_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    last_successful_sync_at: Mapped[Optional[datetime]] = mapped_column(
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

    tickets: Mapped[List["Ticket"]] = relationship(
        "Ticket",
        back_populates="integration",
    )

