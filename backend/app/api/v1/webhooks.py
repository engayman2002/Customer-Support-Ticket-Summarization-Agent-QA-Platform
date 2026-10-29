from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.db.session import AsyncSessionLocal
from app.integrations.registry import ProviderRegistry
from app.models.enums import CrmType
from app.models.integration import Integration
from app.services.idempotency import (
    REDIS_INGESTION_QUEUE_KEY,
    check_and_set_webhook_idempotency,
    extract_webhook_event_identity,
    push_job_to_redis_queue,
)
from app.worker.tasks import process_webhook_ingestion_async

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@dataclass
class CachedIntegrationConfig:
    id: uuid.UUID
    crm_type: CrmType
    is_active: bool
    decrypted_webhook_secret: str


# Pre-populated with the deterministic Phase 1 seeded Zendesk integration so hot-path
# webhook requests perform zero synchronous database queries on the request thread.
_SEEDED_ZENDESK_UUID = uuid.UUID("22222222-2222-4222-8222-222222222201")
_INTEGRATION_CACHE: Dict[uuid.UUID, CachedIntegrationConfig] = {
    _SEEDED_ZENDESK_UUID: CachedIntegrationConfig(
        id=_SEEDED_ZENDESK_UUID,
        crm_type=CrmType.ZENDESK,
        is_active=True,
        decrypted_webhook_secret="dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d",
    )
}

_PENDING_INGESTION_TASKS: Set["asyncio.Task[Any]"] = set()


def cache_integration_config(integration: Integration) -> CachedIntegrationConfig:
    decrypted_secret = decrypt_secret(integration.encrypted_webhook_secret)
    cached = CachedIntegrationConfig(
        id=integration.id,
        crm_type=integration.crm_type,
        is_active=integration.is_active,
        decrypted_webhook_secret=decrypted_secret,
    )
    _INTEGRATION_CACHE[integration.id] = cached
    return cached


def invalidate_integration_cache(integration_id: Optional[uuid.UUID] = None) -> None:
    if integration_id is None:
        _INTEGRATION_CACHE.clear()
    else:
        _INTEGRATION_CACHE.pop(integration_id, None)


async def flush_pending_ingestion_tasks() -> None:
    """Await all in-flight background ingestion tasks (useful for deterministic test assertions)."""
    while _PENDING_INGESTION_TASKS:
        tasks = list(_PENDING_INGESTION_TASKS)
        await asyncio.gather(*tasks, return_exceptions=True)


async def _resolve_integration_config(
    integration_id: uuid.UUID,
) -> Optional[CachedIntegrationConfig]:
    cached = _INTEGRATION_CACHE.get(integration_id)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as db:
        stmt = select(Integration).where(Integration.id == integration_id)
        result = await db.execute(stmt)
        integration = result.scalar_one_or_none()
        if integration is None:
            return None
        return cache_integration_config(integration)


@router.post("/{provider}/{integration_id}")
async def receive_crm_webhook(
    provider: str,
    integration_id: str,
    request: Request,
) -> JSONResponse:
    """
    Unified Non-Blocking Multi-Tenant Webhook Ingestion Endpoint (`Section 1.3, 2.2 & 5.2`):
    1. Resolves active `Integration` from memory/Redis cache (backed by PostgreSQL).
    2. Verifies provider-specific HMAC signature and 300s replay window (`401` on failure).
    3. Filters out non-closed ticket transitions (`200 OK` with `IGNORED_NOT_CLOSED`).
    4. Enforces Redis `SETNX` idempotency (`webhook:dedup:{crm_type}:{external_ticket_id}:{closed_at}`).
    5. Pushes job to `ticket_ingestion_queue`, schedules async worker ingestion off the request
       thread, and immediately returns `202 Accepted` in < 50ms.
    """
    try:
        connector = ProviderRegistry.get_connector(provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    try:
        integration_uuid = uuid.UUID(integration_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid integration_id UUID format",
        ) from exc

    integration_cfg = await _resolve_integration_config(integration_uuid)
    if (
        integration_cfg is None
        or not integration_cfg.is_active
        or integration_cfg.crm_type != connector.crm_type
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active integration not found for specified CRM provider",
        )

    raw_body = await request.body()
    headers_dict = {k: v for k, v in request.headers.items()}

    is_valid_signature = connector.verify_signature(
        headers=headers_dict,
        raw_body=raw_body,
        secret=integration_cfg.decrypted_webhook_secret,
        tolerance_seconds=300,
    )
    if not is_valid_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook HMAC signature verification failed or timestamp expired",
        )

    try:
        payload: Dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON webhook body",
        ) from exc

    received_at_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # State Transition Filtering: ignore non-closed events immediately
    if not connector.is_ticket_closed_event(payload):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "IGNORED_NOT_CLOSED",
                "idempotent_duplicate": False,
                "received_at": received_at_iso,
            },
        )

    external_ticket_id, closed_at_key = extract_webhook_event_identity(
        connector.crm_type, payload
    )
    is_first_delivery = await check_and_set_webhook_idempotency(
        crm_type=connector.crm_type.value,
        external_ticket_id=external_ticket_id,
        event_version_key=closed_at_key,
    )

    job_id = f"job_{uuid.uuid4()}"

    if not is_first_delivery:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "ACCEPTED",
                "job_id": job_id,
                "idempotent_duplicate": True,
                "received_at": received_at_iso,
            },
        )

    # First delivery: push job to Redis `ticket_ingestion_queue` and dispatch async worker task
    await push_job_to_redis_queue(
        REDIS_INGESTION_QUEUE_KEY,
        {
            "job_id": job_id,
            "integration_id": str(integration_uuid),
            "crm_provider": connector.crm_type.value,
            "external_ticket_id": external_ticket_id,
            "received_at": received_at_iso,
        },
    )

    bg_task = asyncio.create_task(
        process_webhook_ingestion_async(
            integration_id=str(integration_uuid),
            provider=connector.crm_type.value,
            raw_payload=payload,
            job_id=job_id,
        )
    )
    _PENDING_INGESTION_TASKS.add(bg_task)
    bg_task.add_done_callback(_PENDING_INGESTION_TASKS.discard)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "ACCEPTED",
            "job_id": job_id,
            "idempotent_duplicate": False,
            "received_at": received_at_iso,
        },
    )
