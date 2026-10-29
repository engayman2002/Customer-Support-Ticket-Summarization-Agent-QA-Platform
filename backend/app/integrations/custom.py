from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from app.integrations.base import BaseCRMConnector
from app.models.enums import CrmType
from app.models.integration import Integration
from app.schemas.ticket_payload import (
    MessageSenderRole,
    NormalizedMessage,
    StandardTicketPayload,
)
from app.services.sanitizer import (
    collapse_consecutive_system_messages,
    sanitize_and_redact_text,
)


class CustomCRMConnector(BaseCRMConnector):
    """
    Custom Internal CRM Connector (Section 2.2 & 2.3):
    - Validates `X-Webhook-Signature` (`HMAC-SHA256`) or `X-Integration-Api-Key` + 300s replay window.
    - Normalizes custom payloads into `StandardTicketPayload`.
    """

    crm_type = CrmType.CUSTOM

    def verify_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        if not secret or raw_body is None:
            return False

        ts_header = self._get_header(headers, "X-Webhook-Timestamp")
        if ts_header is not None and not self._is_timestamp_within_window(
            ts_header, tolerance_seconds
        ):
            return False

        sig_header = self._get_header(headers, "X-Webhook-Signature")
        if sig_header:
            cleaned_sig = sig_header.strip()
            if cleaned_sig.lower().startswith("sha256="):
                cleaned_sig = cleaned_sig[7:]

            digest_raw = hmac.new(
                secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).digest()
            expected_hex = digest_raw.hex()
            expected_b64 = base64.b64encode(digest_raw).decode("ascii")

            if hmac.compare_digest(expected_hex, cleaned_sig) or hmac.compare_digest(
                expected_b64, cleaned_sig
            ):
                return True

            if ts_header:
                ts_digest = hmac.new(
                    secret.encode("utf-8"),
                    ts_header.strip().encode("utf-8") + raw_body,
                    hashlib.sha256,
                ).hexdigest()
                if hmac.compare_digest(ts_digest, cleaned_sig):
                    return True

            return False

        api_key_header = self._get_header(headers, "X-Integration-Api-Key")
        if api_key_header:
            return hmac.compare_digest(api_key_header.strip(), secret)

        return False

    def is_ticket_closed_event(self, payload: Dict[str, Any]) -> bool:
        ticket_obj = (
            payload.get("ticket")
            if isinstance(payload.get("ticket"), dict)
            else payload
        )
        status_val = str(
            ticket_obj.get("status") or payload.get("status") or ""
        ).strip().lower()
        return status_val in {"closed", "solved", "resolved", "completed"}

    async def fetch_full_transcript(
        self,
        external_ticket_id: str,
        integration: Integration,
    ) -> Dict[str, Any]:
        return {
            "external_ticket_id": external_ticket_id,
            "messages": [],
        }

    def normalize_payload(
        self,
        raw_payload: Dict[str, Any],
        integration_id: Union[str, uuid.UUID],
        transcript_data: Optional[Dict[str, Any]] = None,
    ) -> StandardTicketPayload:
        ticket: Dict[str, Any] = (
            raw_payload.get("ticket")
            if isinstance(raw_payload.get("ticket"), dict)
            else raw_payload
        )

        external_ticket_id = str(
            ticket.get("external_ticket_id")
            or ticket.get("id")
            or "CUST-UNKNOWN"
        )
        external_agent_id = str(
            ticket.get("external_agent_id")
            or ticket.get("agent_id")
            or ticket.get("assignee_id")
            or "custom_agent_101"
        )
        agent_email = str(
            ticket.get("agent_email")
            or raw_payload.get("agent_email")
            or f"{external_agent_id}@qa-platform.local"
        )
        agent_name = ticket.get("agent_name") or raw_payload.get("agent_name")
        customer_identifier = self._anonymize_customer_id(
            ticket.get("customer_identifier")
            or ticket.get("customer_id")
            or ticket.get("customer_email")
            or "custom_customer"
        )
        subject = str(ticket.get("subject") or "Custom Support Ticket")
        channel = self._map_channel(ticket.get("channel") or "API")
        priority = self._map_priority(ticket.get("priority") or "NORMAL")
        tags = [str(t) for t in (ticket.get("tags") or [])]

        created_at = self._parse_timestamp(ticket.get("created_at")) or datetime.now(
            timezone.utc
        )
        closed_at = (
            self._parse_timestamp(
                ticket.get("closed_at") or ticket.get("updated_at")
            )
            or created_at
        )

        raw_messages: List[Dict[str, Any]] = (
            (transcript_data or {}).get("messages")
            or ticket.get("messages")
            or raw_payload.get("messages")
            or []
        )

        normalized_messages: List[NormalizedMessage] = []
        for idx, msg in enumerate(raw_messages):
            if not isinstance(msg, dict):
                continue

            if msg.get("is_internal_note") is True:
                continue

            role_str = str(msg.get("sender_role") or "CUSTOMER").upper()
            if role_str not in {"CUSTOMER", "AGENT", "SYSTEM", "BOT"}:
                role_str = "CUSTOMER"

            raw_text = str(msg.get("content") or msg.get("body") or "")
            msg_ts = (
                self._parse_timestamp(
                    msg.get("timestamp") or msg.get("created_at")
                )
                or created_at
            )
            normalized_messages.append(
                NormalizedMessage(
                    message_id=str(
                        msg.get("message_id")
                        or msg.get("id")
                        or f"cust_msg_{idx + 1}"
                    ),
                    sender_role=MessageSenderRole(role_str),
                    sender_name=msg.get("sender_name"),
                    timestamp=msg_ts,
                    content=sanitize_and_redact_text(raw_text),
                    is_internal_note=False,
                )
            )

        if not normalized_messages:
            normalized_messages.append(
                NormalizedMessage(
                    message_id=f"cust_msg_{external_ticket_id}_1",
                    sender_role=MessageSenderRole.CUSTOMER,
                    sender_name="Customer",
                    timestamp=created_at,
                    content=sanitize_and_redact_text(
                        str(ticket.get("description") or subject)
                    ),
                    is_internal_note=False,
                )
            )

        normalized_messages = collapse_consecutive_system_messages(
            normalized_messages
        )

        return StandardTicketPayload(
            integration_id=uuid.UUID(str(integration_id)),
            crm_provider=CrmType.CUSTOM,
            external_ticket_id=external_ticket_id,
            external_agent_id=external_agent_id,
            agent_email=agent_email,
            agent_name=agent_name,
            customer_identifier=customer_identifier,
            subject=subject,
            channel=channel,
            priority=priority,
            tags=tags,
            created_at=created_at,
            closed_at=closed_at,
            first_response_time_seconds=ticket.get(
                "first_response_time_seconds"
            ),
            total_resolution_time_seconds=ticket.get(
                "total_resolution_time_seconds"
            )
            or max(0, int((closed_at - created_at).total_seconds())),
            messages=normalized_messages,
        )

    async def poll_closed_tickets(
        self,
        since_timestamp: datetime,
        integration: Integration,
    ) -> List[StandardTicketPayload]:
        return []

