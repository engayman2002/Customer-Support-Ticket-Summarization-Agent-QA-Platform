from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CrmType, TicketChannel, TicketPriority


class MessageSenderRole(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    BOT = "BOT"


class NormalizedMessage(BaseModel):
    """Canonical conversation message turn inside `StandardTicketPayload`."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(..., min_length=1)
    sender_role: MessageSenderRole
    sender_name: Optional[str] = None
    timestamp: datetime
    content: str = Field(
        ...,
        min_length=1,
        description="Plain-text stripped of HTML boilerplate and PII-redacted",
    )
    is_internal_note: bool = False


class StandardTicketPayload(BaseModel):
    """
    Canonical `StandardTicketPayload` contract (Section 2.3) produced by all CRM adapters
    before entering the database and LangChain + Groq QA pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    integration_id: uuid.UUID
    crm_provider: CrmType
    external_ticket_id: str = Field(..., min_length=1)
    external_agent_id: str = Field(..., min_length=1)
    agent_email: str = Field(..., min_length=3)
    agent_name: Optional[str] = None
    customer_identifier: str = Field(
        ...,
        min_length=1,
        description="Anonymized or hashed customer ID/email",
    )
    subject: str = Field(default="Support Ticket")
    channel: TicketChannel = Field(default=TicketChannel.EMAIL)
    priority: TicketPriority = Field(default=TicketPriority.NORMAL)
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    closed_at: datetime
    first_response_time_seconds: Optional[int] = Field(default=None, ge=0)
    total_resolution_time_seconds: Optional[int] = Field(default=None, ge=0)
    messages: List[NormalizedMessage] = Field(..., min_length=1)

    @field_validator("agent_email")
    @classmethod
    def validate_agent_email(cls, value: str) -> str:
        cleaned = value.strip()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError(f"Invalid agent_email format: '{value}'")
        return cleaned

