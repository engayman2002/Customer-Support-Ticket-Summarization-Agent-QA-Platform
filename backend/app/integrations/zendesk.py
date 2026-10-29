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


class ZendeskConnector(BaseCRMConnector):
    """
    Zendesk CRM Connector (Section 2.2 & 2.3):
    - Validates `X-Zendesk-Webhook-Signature` and `X-Zendesk-Webhook-Signature-Timestamp`
      using `Base64(HMAC-SHA256(timestamp + raw_body, secret))` with 300s replay window.
    - Normalizes Zendesk `ticket` and `comments[]` into `StandardTicketPayload`.
    """

    crm_type = CrmType.ZENDESK

    def verify_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        signature = self._get_header(headers, "X-Zendesk-Webhook-Signature")
        timestamp = self._get_header(
            headers, "X-Zendesk-Webhook-Signature-Timestamp"
        )

        if not signature or not timestamp or not secret or raw_body is None:
            return False

        if not self._is_timestamp_within_window(timestamp, tolerance_seconds):
            return False

        signing_payload = timestamp.strip().encode("utf-8") + raw_body
        digest = hmac.new(
            secret.encode("utf-8"),
            signing_payload,
            hashlib.sha256,
        ).digest()
        expected_signature = base64.b64encode(digest).decode("ascii")

        return hmac.compare_digest(expected_signature, signature.strip())

    def is_ticket_closed_event(self, payload: Dict[str, Any]) -> bool:
        ticket_obj = payload.get("ticket")
        if isinstance(ticket_obj, dict) and "status" in ticket_obj:
            status_val = str(ticket_obj.get("status") or "").strip().lower()
            return status_val in {"closed", "solved"}

        detail_obj = payload.get("detail")
        if isinstance(detail_obj, dict) and "status" in detail_obj:
            status_val = str(detail_obj.get("status") or "").strip().lower()
            return status_val in {"closed", "solved"}

        status_val = str(payload.get("status") or "").strip().lower()
        return status_val in {"closed", "solved"}

    async def fetch_full_transcript(
        self,
        external_ticket_id: str,
        integration: Integration,
    ) -> Dict[str, Any]:
        return {
            "external_ticket_id": external_ticket_id,
            "comments": [],
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
            ticket.get("id") or ticket.get("external_ticket_id") or "ZD-UNKNOWN"
        )
        external_agent_id = str(
            ticket.get("assignee_id")
            or ticket.get("external_agent_id")
            or "zd_agent_101"
        )
        agent_email = str(
            ticket.get("assignee_email")
            or ticket.get("agent_email")
            or raw_payload.get("agent_email")
            or f"{external_agent_id}@qa-platform.local"
        )
        agent_name = (
            ticket.get("assignee_name")
            or ticket.get("agent_name")
            or raw_payload.get("agent_name")
        )
        raw_customer = (
            ticket.get("requester_id")
            or ticket.get("requester_email")
            or ticket.get("customer_identifier")
            or raw_payload.get("customer_identifier")
            or "zendesk_customer"
        )
        customer_identifier = self._anonymize_customer_id(raw_customer)
        subject = str(ticket.get("subject") or "Zendesk Support Inquiry")

        via_obj = ticket.get("via")
        raw_channel = (
            via_obj.get("channel")
            if isinstance(via_obj, dict)
            else ticket.get("channel")
        )
        channel = self._map_channel(raw_channel)
        priority = self._map_priority(ticket.get("priority"))
        tags = [str(t) for t in (ticket.get("tags") or [])]

        created_at = self._parse_timestamp(ticket.get("created_at")) or datetime.now(
            timezone.utc
        )
        closed_at = (
            self._parse_timestamp(
                ticket.get("updated_at")
                or ticket.get("closed_at")
                or raw_payload.get("closed_at")
            )
            or created_at
        )

        raw_comments: List[Dict[str, Any]] = (
            (transcript_data or {}).get("comments")
            or ticket.get("comments")
            or raw_payload.get("comments")
            or ticket.get("messages")
            or raw_payload.get("messages")
            or []
        )

        normalized_messages: List[NormalizedMessage] = []
        for idx, comment in enumerate(raw_comments):
            if not isinstance(comment, dict):
                continue

            # Filter out private internal notes when `public` flag is explicitly False
            is_public = comment.get("public", True)
            if is_public is False:
                continue

            raw_role = str(
                comment.get("sender_role")
                or comment.get("author_role")
                or (
                    "AGENT"
                    if str(comment.get("author_id") or "") == external_agent_id
                    else "CUSTOMER"
                )
            ).upper()
            if raw_role not in {"CUSTOMER", "AGENT", "SYSTEM", "BOT"}:
                raw_role = "CUSTOMER"

            raw_text = str(
                comment.get("body")
                or comment.get("html_body")
                or comment.get("content")
                or comment.get("plain_body")
                or ""
            )
            cleaned_text = sanitize_and_redact_text(raw_text)

            msg_ts = (
                self._parse_timestamp(
                    comment.get("created_at") or comment.get("timestamp")
                )
                or created_at
            )
            normalized_messages.append(
                NormalizedMessage(
                    message_id=str(
                        comment.get("id")
                        or comment.get("message_id")
                        or f"zd_msg_{idx + 1}"
                    ),
                    sender_role=MessageSenderRole(raw_role),
                    sender_name=comment.get("author_name")
                    or comment.get("sender_name"),
                    timestamp=msg_ts,
                    content=cleaned_text,
                    is_internal_note=not bool(is_public),
                )
            )

        if not normalized_messages:
            fallback_desc = sanitize_and_redact_text(
                str(ticket.get("description") or subject)
            )
            normalized_messages.append(
                NormalizedMessage(
                    message_id=f"zd_msg_{external_ticket_id}_1",
                    sender_role=MessageSenderRole.CUSTOMER,
                    sender_name="Customer",
                    timestamp=created_at,
                    content=fallback_desc,
                    is_internal_note=False,
                )
            )

        normalized_messages = collapse_consecutive_system_messages(
            normalized_messages
        )

        total_res_seconds = ticket.get("total_resolution_time_seconds")
        if total_res_seconds is None:
            total_res_seconds = max(
                0, int((closed_at - created_at).total_seconds())
            )

        return StandardTicketPayload(
            integration_id=uuid.UUID(str(integration_id)),
            crm_provider=CrmType.ZENDESK,
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
            total_resolution_time_seconds=total_res_seconds,
            messages=normalized_messages,
        )

    async def poll_closed_tickets(
        self,
        since_timestamp: datetime,
        integration: Integration,
    ) -> List[StandardTicketPayload]:
        return []

