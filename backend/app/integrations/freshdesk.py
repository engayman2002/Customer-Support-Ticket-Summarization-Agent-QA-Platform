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


class FreshdeskConnector(BaseCRMConnector):
    """
    Freshdesk CRM Connector (Section 2.2 & 2.3):
    - Validates `X-Webhook-Signature` (`HMAC-SHA256`) or `X-Integration-Api-Key` + 300s replay window.
    - Maps Freshdesk `ticket`, `stats.closed_at`, and `conversations[]` (`private == false`) into `StandardTicketPayload`.
    """

    crm_type = CrmType.FRESHDESK

    def verify_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        if not secret or raw_body is None:
            return False

        ts_header = self._get_header(
            headers, "X-Webhook-Timestamp"
        ) or self._get_header(headers, "X-Freshdesk-Timestamp")
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
        raw_status = ticket_obj.get("status")
        if raw_status is None:
            raw_status = payload.get("status")

        if isinstance(raw_status, int):
            return raw_status in {4, 5}

        status_str = str(raw_status or "").strip().lower()
        return status_str in {"4", "5", "closed", "resolved", "solved"}

    async def fetch_full_transcript(
        self,
        external_ticket_id: str,
        integration: Integration,
    ) -> Dict[str, Any]:
        return {
            "external_ticket_id": external_ticket_id,
            "conversations": [],
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
            ticket.get("id") or ticket.get("external_ticket_id") or "FD-UNKNOWN"
        )
        external_agent_id = str(
            ticket.get("responder_id")
            or ticket.get("external_agent_id")
            or "fd_agent_101"
        )
        agent_email = str(
            ticket.get("responder_email")
            or ticket.get("agent_email")
            or raw_payload.get("agent_email")
            or f"{external_agent_id}@qa-platform.local"
        )
        agent_name = (
            ticket.get("responder_name")
            or ticket.get("agent_name")
            or raw_payload.get("agent_name")
        )
        raw_customer = (
            ticket.get("requester_id")
            or ticket.get("requester_email")
            or ticket.get("customer_identifier")
            or "freshdesk_customer"
        )
        customer_identifier = self._anonymize_customer_id(raw_customer)
        subject = str(ticket.get("subject") or "Freshdesk Support Ticket")
        channel = self._map_channel(
            ticket.get("source") or ticket.get("channel")
        )
        priority = self._map_priority(ticket.get("priority"))
        tags = [str(t) for t in (ticket.get("tags") or [])]

        created_at = self._parse_timestamp(ticket.get("created_at")) or datetime.now(
            timezone.utc
        )
        stats_obj = (
            ticket.get("stats") if isinstance(ticket.get("stats"), dict) else {}
        )
        closed_at = (
            self._parse_timestamp(
                stats_obj.get("closed_at")
                or stats_obj.get("resolved_at")
                or ticket.get("updated_at")
                or ticket.get("closed_at")
            )
            or created_at
        )

        raw_conversations: List[Dict[str, Any]] = (
            (transcript_data or {}).get("conversations")
            or ticket.get("conversations")
            or raw_payload.get("conversations")
            or ticket.get("messages")
            or raw_payload.get("messages")
            or []
        )

        normalized_messages: List[NormalizedMessage] = []
        for idx, conv in enumerate(raw_conversations):
            if not isinstance(conv, dict):
                continue

            if conv.get("private") is True:
                continue

            incoming = conv.get("incoming")
            if "sender_role" in conv:
                role_str = str(conv["sender_role"]).upper()
            elif incoming is True:
                role_str = "CUSTOMER"
            elif incoming is False:
                role_str = "AGENT"
            else:
                role_str = (
                    "AGENT"
                    if str(conv.get("user_id") or "") == external_agent_id
                    else "CUSTOMER"
                )

            if role_str not in {"CUSTOMER", "AGENT", "SYSTEM", "BOT"}:
                role_str = "CUSTOMER"

            raw_text = str(
                conv.get("body_text")
                or conv.get("body")
                or conv.get("content")
                or ""
            )
            msg_ts = (
                self._parse_timestamp(
                    conv.get("created_at") or conv.get("timestamp")
                )
                or created_at
            )
            normalized_messages.append(
                NormalizedMessage(
                    message_id=str(
                        conv.get("id")
                        or conv.get("message_id")
                        or f"fd_msg_{idx + 1}"
                    ),
                    sender_role=MessageSenderRole(role_str),
                    sender_name=conv.get("sender_name"),
                    timestamp=msg_ts,
                    content=sanitize_and_redact_text(raw_text),
                    is_internal_note=False,
                )
            )

        if not normalized_messages:
            fallback_text = sanitize_and_redact_text(
                str(
                    ticket.get("description_text")
                    or ticket.get("description")
                    or subject
                )
            )
            normalized_messages.append(
                NormalizedMessage(
                    message_id=f"fd_msg_{external_ticket_id}_1",
                    sender_role=MessageSenderRole.CUSTOMER,
                    sender_name="Customer",
                    timestamp=created_at,
                    content=fallback_text,
                    is_internal_note=False,
                )
            )

        normalized_messages = collapse_consecutive_system_messages(
            normalized_messages
        )

        return StandardTicketPayload(
            integration_id=uuid.UUID(str(integration_id)),
            crm_provider=CrmType.FRESHDESK,
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
            total_resolution_time_seconds=max(
                0, int((closed_at - created_at).total_seconds())
            ),
            messages=normalized_messages,
        )

    async def poll_closed_tickets(
        self,
        since_timestamp: datetime,
        integration: Integration,
    ) -> List[StandardTicketPayload]:
        return []

