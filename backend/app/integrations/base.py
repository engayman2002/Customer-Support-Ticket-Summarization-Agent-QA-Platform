from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Union

from app.models.enums import CrmType, TicketChannel, TicketPriority
from app.models.integration import Integration
from app.schemas.ticket_payload import StandardTicketPayload


class BaseCRMConnector(ABC):
    """
    Abstract Strategy/Adapter interface (Section 2.1) implemented by all external CRM connectors.
    """

    crm_type: CrmType

    @abstractmethod
    def verify_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        """
        Verify the provider-specific cryptographic HMAC signature and enforce
        the replay protection window (`tolerance_seconds`, default 300s).
        """

    @abstractmethod
    def is_ticket_closed_event(self, payload: Dict[str, Any]) -> bool:
        """
        Return True only if the webhook payload represents a transition into a
        terminal closed/solved ticket state.
        """

    @abstractmethod
    async def fetch_full_transcript(
        self,
        external_ticket_id: str,
        integration: Integration,
    ) -> Dict[str, Any]:
        """
        Fetch full conversation thread from the originating CRM REST API when a
        webhook payload only includes ticket metadata.
        """

    @abstractmethod
    def normalize_payload(
        self,
        raw_payload: Dict[str, Any],
        integration_id: Union[str, uuid.UUID],
        transcript_data: Optional[Dict[str, Any]] = None,
    ) -> StandardTicketPayload:
        """
        Transform proprietary CRM webhook/API structures into the canonical,
        PII-redacted `StandardTicketPayload` contract.
        """

    @abstractmethod
    async def poll_closed_tickets(
        self,
        since_timestamp: datetime,
        integration: Integration,
    ) -> List[StandardTicketPayload]:
        """
        Fallback delta-sync polling mechanism querying closed tickets updated since `since_timestamp`.
        """

    @staticmethod
    def _get_header(headers: Mapping[str, str], target_key: str) -> Optional[str]:
        """Case-insensitive HTTP header lookup."""
        target_lower = target_key.lower()
        for k, v in headers.items():
            if k.lower() == target_lower:
                return v
        return None

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """Parse Unix seconds, Unix milliseconds, or ISO-8601 strings into UTC datetime."""
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e11:  # milliseconds -> seconds
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            # Check if numeric epoch string
            try:
                ts_num = float(stripped)
                if ts_num > 1e11:
                    ts_num /= 1000.0
                return datetime.fromtimestamp(ts_num, tz=timezone.utc)
            except ValueError:
                pass

            # Parse ISO-8601
            iso_str = (
                stripped[:-1] + "+00:00"
                if stripped.endswith("Z")
                else stripped
            )
            try:
                dt = datetime.fromisoformat(iso_str)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                return None

        return None

    @classmethod
    def _is_timestamp_within_window(
        cls,
        timestamp_value: Any,
        tolerance_seconds: int = 300,
    ) -> bool:
        """
        Enforce replay attack protection: reject timestamps deviating from server UTC
        clock by more than `tolerance_seconds` (300 seconds / 5 minutes).
        """
        parsed = cls._parse_timestamp(timestamp_value)
        if parsed is None:
            return False
        now_utc = datetime.now(timezone.utc)
        delta_seconds = abs((now_utc - parsed).total_seconds())
        return delta_seconds <= tolerance_seconds

    @staticmethod
    def _anonymize_customer_id(raw_customer: Any) -> str:
        """
        Anonymize or hash customer email/ID into a deterministic non-PII identifier.
        """
        raw_str = str(raw_customer or "anonymous").strip()
        if not raw_str:
            raw_str = "anonymous"
        if raw_str.startswith("cust_hash_") or raw_str.startswith("cust_"):
            return raw_str
        digest = hashlib.sha256(raw_str.lower().encode("utf-8")).hexdigest()[:12]
        return f"cust_hash_{digest}"

    @staticmethod
    def _map_channel(raw_channel: Any) -> TicketChannel:
        """Map CRM channel identifiers or Freshdesk numeric source codes to `TicketChannel`."""
        if isinstance(raw_channel, int) or (
            isinstance(raw_channel, str) and raw_channel.strip().isdigit()
        ):
            code = int(raw_channel)
            freshdesk_map = {
                1: TicketChannel.EMAIL,
                2: TicketChannel.WEB_FORM,
                3: TicketChannel.LIVE_CHAT,
                7: TicketChannel.LIVE_CHAT,
                8: TicketChannel.SOCIAL,
                9: TicketChannel.API,
            }
            return freshdesk_map.get(code, TicketChannel.EMAIL)

        val = str(raw_channel or "EMAIL").strip().upper()
        channel_aliases = {
            "EMAIL": TicketChannel.EMAIL,
            "MAIL": TicketChannel.EMAIL,
            "LIVE_CHAT": TicketChannel.LIVE_CHAT,
            "CHAT": TicketChannel.LIVE_CHAT,
            "MESSENGER": TicketChannel.LIVE_CHAT,
            "CONVERSATION": TicketChannel.LIVE_CHAT,
            "SOCIAL": TicketChannel.SOCIAL,
            "TWITTER": TicketChannel.SOCIAL,
            "FACEBOOK": TicketChannel.SOCIAL,
            "WEB_FORM": TicketChannel.WEB_FORM,
            "WEB": TicketChannel.WEB_FORM,
            "PORTAL": TicketChannel.WEB_FORM,
            "FORM": TicketChannel.WEB_FORM,
            "API": TicketChannel.API,
        }
        return channel_aliases.get(val, TicketChannel.EMAIL)

    @staticmethod
    def _map_priority(raw_priority: Any) -> TicketPriority:
        """Map CRM priority strings or Freshdesk numeric priority codes (1-4) to `TicketPriority`."""
        if isinstance(raw_priority, int) or (
            isinstance(raw_priority, str) and raw_priority.strip().isdigit()
        ):
            code = int(raw_priority)
            freshdesk_priority_map = {
                1: TicketPriority.LOW,
                2: TicketPriority.NORMAL,
                3: TicketPriority.HIGH,
                4: TicketPriority.URGENT,
            }
            return freshdesk_priority_map.get(code, TicketPriority.NORMAL)

        val = str(raw_priority or "NORMAL").strip().upper()
        priority_aliases = {
            "LOW": TicketPriority.LOW,
            "NORMAL": TicketPriority.NORMAL,
            "MEDIUM": TicketPriority.NORMAL,
            "STANDARD": TicketPriority.NORMAL,
            "HIGH": TicketPriority.HIGH,
            "URGENT": TicketPriority.URGENT,
            "CRITICAL": TicketPriority.URGENT,
        }
        return priority_aliases.get(val, TicketPriority.NORMAL)

