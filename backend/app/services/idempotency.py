from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Tuple
from weakref import WeakKeyDictionary

import redis.asyncio as aioredis

from app.core.config import settings
from app.models.enums import CrmType

WEBHOOK_DEDUP_TTL_SECONDS = 86400  # 24 hours
REDIS_INGESTION_QUEUE_KEY = "ticket_ingestion_queue"
REDIS_AI_EVALUATION_QUEUE_KEY = "ai_evaluation_queue"

_LOOP_REDIS_CLIENTS: "WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis]" = (
    WeakKeyDictionary()
)


def get_redis_client() -> aioredis.Redis:
    """
    Return a pooled async Redis client bound to the currently running event loop.
    Avoids per-request connection overhead (<1ms Redis commands) and prevents
    cross-loop errors across `pytest-asyncio` test functions.
    """
    loop = asyncio.get_running_loop()
    client = _LOOP_REDIS_CLIENTS.get(loop)
    if client is None:
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=256,
        )
        _LOOP_REDIS_CLIENTS[loop] = client
    return client


def build_webhook_dedup_key(
    crm_type: str,
    external_ticket_id: str,
    event_version_key: str,
) -> str:
    """Construct the canonical Redis idempotency key (`Section 1.3`)."""
    provider = str(crm_type).strip().upper()
    ext_id = str(external_ticket_id).strip()
    version = str(event_version_key).strip()
    return f"webhook:dedup:{provider}:{ext_id}:{version}"


async def check_and_set_webhook_idempotency(
    crm_type: str,
    external_ticket_id: str,
    event_version_key: str,
    ttl_seconds: int = WEBHOOK_DEDUP_TTL_SECONDS,
) -> bool:
    """
    Execute atomic Redis `SET <key> "1" NX EX <ttl_seconds>`.
    Returns True if this is a brand-new webhook delivery (lock acquired),
    or False if this exact `(crm_type, external_ticket_id, closed_at)` was already received.
    """
    redis_client = get_redis_client()
    dedup_key = build_webhook_dedup_key(
        crm_type=crm_type,
        external_ticket_id=external_ticket_id,
        event_version_key=event_version_key,
    )
    was_set = await redis_client.set(dedup_key, "1", nx=True, ex=ttl_seconds)
    return bool(was_set)


def extract_webhook_event_identity(
    crm_type: CrmType,
    payload: Dict[str, Any],
) -> Tuple[str, str]:
    """
    O(1) extraction of `(external_ticket_id, closed_at_or_updated_at)` from raw CRM webhook JSON
    for immediate Redis `SETNX` idempotency checking on the request thread.
    """
    if crm_type == CrmType.ZENDESK:
        ticket = (
            payload.get("ticket")
            if isinstance(payload.get("ticket"), dict)
            else payload
        )
        ext_id = str(
            ticket.get("id") or ticket.get("external_ticket_id") or "unknown"
        )
        closed_key = str(
            ticket.get("updated_at")
            or ticket.get("closed_at")
            or payload.get("closed_at")
            or "latest"
        )
        return ext_id, closed_key

    if crm_type == CrmType.INTERCOM:
        conv = (
            payload.get("conversation")
            or (payload.get("data") or {}).get("item")
            or payload
        )
        if not isinstance(conv, dict):
            conv = payload
        ext_id = str(
            conv.get("id") or conv.get("external_ticket_id") or "unknown"
        )
        stats = (
            conv.get("statistics")
            if isinstance(conv.get("statistics"), dict)
            else {}
        )
        closed_key = str(
            stats.get("last_close_at")
            or conv.get("updated_at")
            or conv.get("closed_at")
            or payload.get("created_at")
            or "latest"
        )
        return ext_id, closed_key

    if crm_type == CrmType.FRESHDESK:
        ticket = (
            payload.get("ticket")
            if isinstance(payload.get("ticket"), dict)
            else payload
        )
        ext_id = str(
            ticket.get("id") or ticket.get("external_ticket_id") or "unknown"
        )
        stats = (
            ticket.get("stats") if isinstance(ticket.get("stats"), dict) else {}
        )
        closed_key = str(
            stats.get("closed_at")
            or stats.get("resolved_at")
            or ticket.get("updated_at")
            or ticket.get("closed_at")
            or "latest"
        )
        return ext_id, closed_key

    # CrmType.CUSTOM
    ticket = (
        payload.get("ticket")
        if isinstance(payload.get("ticket"), dict)
        else payload
    )
    ext_id = str(
        ticket.get("external_ticket_id") or ticket.get("id") or "unknown"
    )
    closed_key = str(
        ticket.get("closed_at")
        or ticket.get("updated_at")
        or payload.get("closed_at")
        or "latest"
    )
    return ext_id, closed_key


async def push_job_to_redis_queue(
    queue_name: str,
    job_envelope: Dict[str, Any],
) -> int:
    """Push a serialized job envelope onto the specified Redis queue list."""
    redis_client = get_redis_client()
    return int(await redis_client.rpush(queue_name, json.dumps(job_envelope)))

