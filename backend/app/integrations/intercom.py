from __future__ import annotations

import hashlib
import hmac
import json
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


class IntercomConnector(BaseCRMConnector):
    """
    Intercom CRM Connector (Section 2.2 & 2.3):
    - Validates `X-Hub-Signature-256` (`sha256=<hex_digest>`) + 300s replay window.
    - Maps `conversation`, `source`, and `conversation_parts` into `StandardTicketPayload`.
    """

    crm_type = CrmType.INTERCOM

    def verify_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        sig_header = self._get_header(headers, "X-Hub-Signature-256")
        if not sig_header or not secret or raw_body is None:
            return False

        # Check explicit timestamp header first; fall back to JSON payload `created_at`
        ts_header = (
            self._get_header(headers, "X-Intercom-Timestamp")
            or self._get_header(headers, "X-Webhook-Timestamp")
            or self._get_header(headers, "X-Hub-Timestamp")
        )
        if ts_header is not None:
            if not self._is_timestamp_within_window(
                ts_header, tolerance_seconds
            ):
                return False
        else:
            try:
                body_json = json.loads(raw_body.decode("utf-8"))
                if isinstance(body_json, dict) and "created_at" in body_json:
                    if not self._is_timestamp_within_window(
                        body_json["created_at"], tolerance_seconds
                    ):
                        return False
            except Exception:
                pass

        expected_hex = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        normalized_sig = sig_header.strip()
        if normalized_sig.lower().startswith("sha256="):
            provided_hex = normalized_sig[7:]
        else:
            provided_hex = normalized_sig

        return hmac.compare_digest(expected_hex, provided_hex)

    def is_ticket_closed_event(self, payload: Dict[str, Any]) -> bool:
        topic = str(payload.get("topic") or "").strip().lower()
        if topic in {
            "conversation.admin.closed",
            "conversation.closed",
            "ticket.closed",
        }:
            return True

        conv = (
            payload.get("conversation")
            or (payload.get("data") or {}).get("item")
            or payload
        )
        if isinstance(conv, dict):
            state_val = str(
                conv.get("state") or conv.get("status") or ""
            ).strip().lower()
            if state_val in {"closed", "resolved", "solved"}:
                return True

        return False

    async def fetch_full_transcript(
        self,
        external_ticket_id: str,
        integration: Integration,
    ) -> Dict[str, Any]:
        return {
            "external_ticket_id": external_ticket_id,
            "conversation_parts": [],
        }

    def normalize_payload(
        self,
        raw_payload: Dict[str, Any],
        integration_id: Union[str, uuid.UUID],
        transcript_data: Optional[Dict[str, Any]] = None,
    ) -> StandardTicketPayload:
        conv: Dict[str, Any] = (
            raw_payload.get("conversation")
            or (raw_payload.get("data") or {}).get("item")
            or raw_payload
        )

        external_ticket_id = str(
            conv.get("id") or conv.get("external_ticket_id") or "IC-UNKNOWN"
        )
        external_agent_id = str(
            conv.get("admin_assignee_id")
            or conv.get("external_agent_id")
            or "ic_agent_101"
        )
        agent_email = str(
            conv.get("agent_email")
            or raw_payload.get("agent_email")
            or f"{external_agent_id}@qa-platform.local"
        )
        agent_name = conv.get("agent_name") or raw_payload.get("agent_name")

        source_obj = conv.get("source") if isinstance(conv.get("source"), dict) else {}
        author_obj = (
            source_obj.get("author")
            if isinstance(source_obj.get("author"), dict)
            else {}
        )
        raw_customer = (
            author_obj.get("id")
            or author_obj.get("email")
            or conv.get("customer_identifier")
            or "intercom_customer"
        )
        customer_identifier = self._anonymize_customer_id(raw_customer)

        subject = str(
            conv.get("title")
            or source_obj.get("subject")
            or conv.get("subject")
            or "Intercom Conversation"
        )
        channel = self._map_channel(
            source_obj.get("delivered_as") or conv.get("channel") or "LIVE_CHAT"
        )
        priority = self._map_priority(conv.get("priority"))

        tags_raw = conv.get("tags")
        if isinstance(tags_raw, dict) and isinstance(tags_raw.get("tags"), list):
            tags = [
                str(t.get("name") if isinstance(t, dict) else t)
                for t in tags_raw["tags"]
            ]
        elif isinstance(tags_raw, list):
            tags = [
                str(t.get("name") if isinstance(t, dict) else t)
                for t in tags_raw
            ]
        else:
            tags = []

        created_at = self._parse_timestamp(conv.get("created_at")) or datetime.now(
            timezone.utc
        )
        stats_obj = (
            conv.get("statistics")
            if isinstance(conv.get("statistics"), dict)
            else {}
        )
        closed_at = (
            self._parse_timestamp(
                stats_obj.get("last_close_at")
                or conv.get("updated_at")
                or conv.get("closed_at")
            )
            or created_at
        )

        normalized_messages: List[NormalizedMessage] = []

        # 1. Initial opening message from `source.body`
        if source_obj.get("body"):
            normalized_messages.append(
                NormalizedMessage(
                    message_id=str(source_obj.get("id") or f"ic_src_{external_ticket_id}"),
                    sender_role=MessageSenderRole.CUSTOMER,
                    sender_name=author_obj.get("name") or "Customer",
                    timestamp=created_at,
                    content=sanitize_and_redact_text(str(source_obj["body"])),
                    is_internal_note=False,
                )
            )

        # 2. Subsequent `conversation_parts`
        parts_container = (
            (transcript_data or {}).get("conversation_parts")
            or conv.get("conversation_parts")
            or conv.get("messages")
            or []
        )
        if isinstance(parts_container, dict):
            parts_list = parts_container.get("conversation_parts") or []
        elif isinstance(parts_container, list):
            parts_list = parts_container
        else:
            parts_list = []

        for idx, part in enumerate(parts_list):
            if not isinstance(part, dict):
                continue

            part_type = str(part.get("part_type") or "comment").lower()
            is_note = part_type == "note" or bool(part.get("is_internal_note", False))
            if is_note:
                continue

            raw_body_text = str(
                part.get("body") or part.get("content") or ""
            ).strip()
            if not raw_body_text:
                continue

            part_author = (
                part.get("author")
                if isinstance(part.get("author"), dict)
                else {}
            )
            author_type = str(
                part.get("sender_role")
                or part_author.get("type")
                or "user"
            ).lower()
            if author_type in {"admin", "agent", "team"}:
                role = MessageSenderRole.AGENT
            elif author_type in {"bot", "operator"}:
                role = MessageSenderRole.BOT
            elif author_type == "system":
                role = MessageSenderRole.SYSTEM
            else:
                role = MessageSenderRole.CUSTOMER

            part_ts = (
                self._parse_timestamp(
                    part.get("created_at") or part.get("timestamp")
                )
                or created_at
            )
            normalized_messages.append(
                NormalizedMessage(
                    message_id=str(
                        part.get("id")
                        or part.get("message_id")
                        or f"ic_part_{idx + 1}"
                    ),
                    sender_role=role,
                    sender_name=part_author.get("name")
                    or part.get("sender_name"),
                    timestamp=part_ts,
                    content=sanitize_and_redact_text(raw_body_text),
                    is_internal_note=False,
                )
            )

        if not normalized_messages:
            normalized_messages.append(
                NormalizedMessage(
                    message_id=f"ic_msg_{external_ticket_id}_1",
                    sender_role=MessageSenderRole.CUSTOMER,
                    sender_name="Customer",
                    timestamp=created_at,
                    content=sanitize_and_redact_text(subject),
                    is_internal_note=False,
                )
            )

        normalized_messages = collapse_consecutive_system_messages(
            normalized_messages
        )

        return StandardTicketPayload(
            integration_id=uuid.UUID(str(integration_id)),
            crm_provider=CrmType.INTERCOM,
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
            first_response_time_seconds=stats_obj.get(
                "time_to_admin_reply"
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

