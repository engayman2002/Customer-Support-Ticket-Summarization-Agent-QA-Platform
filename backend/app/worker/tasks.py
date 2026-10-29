from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations.registry import ProviderRegistry
from app.models.enums import ProcessingStatus
from app.models.integration import Integration
from app.models.ticket import Ticket
from app.services.ingestion_service import (
    ingest_normalized_ticket,
    reconcile_integration_closed_tickets,
)
from app.worker.celery_app import (
    AI_EVALUATION_DLQ_NAME,
    AI_EVALUATION_QUEUE_NAME,
    INGESTION_QUEUE_NAME,
    celery_app,
)


def _run_async(coro: Any) -> Any:
    """Execute an async coroutine safely from a synchronous Celery worker thread."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return asyncio.ensure_future(coro)
    return asyncio.run(coro)


async def process_webhook_ingestion_async(
    integration_id: str,
    provider: str,
    raw_payload: Dict[str, Any],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async implementation of `process_webhook_ingestion_task`:
    1. Resolves the CRM connector via `ProviderRegistry`.
    2. Normalizes and PII-scrubs the raw webhook payload into `StandardTicketPayload`.
    3. Persists the `Ticket` record with `processing_status = QUEUED`.
    4. Enqueues `evaluate_ticket_ai_qa_task` on `ai_evaluation_queue`.
    """
    connector = ProviderRegistry.get_connector(provider)
    normalized_payload = connector.normalize_payload(
        raw_payload=raw_payload,
        integration_id=integration_id,
    )

    async with AsyncSessionLocal() as db:
        ticket, created_new = await ingest_normalized_ticket(
            db,
            normalized_payload,
            enqueue_ai_eval=True,
        )

    return {
        "job_id": job_id or f"job_{uuid.uuid4()}",
        "ticket_id": str(ticket.id),
        "external_ticket_id": ticket.external_ticket_id,
        "processing_status": ticket.processing_status.value,
        "created_new": created_new,
    }


@celery_app.task(
    name="app.worker.tasks.process_webhook_ingestion_task",
    queue=INGESTION_QUEUE_NAME,
)
def process_webhook_ingestion_task(
    integration_id: str,
    provider: str,
    raw_payload: Dict[str, Any],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Celery task consuming `ingestion_queue` to normalize and persist closed tickets."""
    return _run_async(
        process_webhook_ingestion_async(
            integration_id=integration_id,
            provider=provider,
            raw_payload=raw_payload,
            job_id=job_id,
        )
    )


async def reconcile_closed_tickets_async(
    integration_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async implementation of the 15-minute Scheduled Delta-Sync Reconciler (Section 2.4).
    """
    summaries: List[Dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        stmt = select(Integration).where(Integration.is_active.is_(True))
        if integration_id is not None:
            stmt = stmt.where(Integration.id == uuid.UUID(str(integration_id)))

        result = await db.execute(stmt)
        integrations = list(result.scalars().all())

        for integration in integrations:
            summary = await reconcile_integration_closed_tickets(
                db, integration
            )
            summaries.append(summary)

    return {
        "reconciled_integrations_count": len(summaries),
        "results": summaries,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


@celery_app.task(
    name="app.worker.tasks.reconcile_closed_tickets_task",
    queue=INGESTION_QUEUE_NAME,
)
def reconcile_closed_tickets_task(
    integration_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Scheduled Celery Beat task (every 15 minutes) polling active CRM integrations
    for closed tickets missed by webhooks.
    """
    return _run_async(
        reconcile_closed_tickets_async(integration_id=integration_id)
    )


@celery_app.task(
    name="app.worker.tasks.evaluate_ticket_ai_qa_task",
    queue=AI_EVALUATION_QUEUE_NAME,
)
def evaluate_ticket_ai_qa_task(ticket_id: str) -> Dict[str, Any]:
    """
    Rate-limited AI evaluation worker task on `ai_evaluation_queue`.
    Phase 2 registers the queue routing and deterministic stub; Phase 3 populates
    the LangChain + Groq (`llama-3.3-70b-versatile`) structured evaluation pipeline.
    """
    return {
        "ticket_id": str(ticket_id),
        "queue": AI_EVALUATION_QUEUE_NAME,
        "status": "QUEUED_FOR_AI_EVALUATION",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }


async def _mark_ticket_failed_retryable_async(
    ticket_id: str,
    error_reason: str,
) -> Dict[str, Any]:
    async with AsyncSessionLocal() as db:
        stmt = select(Ticket).where(Ticket.id == uuid.UUID(str(ticket_id)))
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()
        if ticket is not None:
            ticket.processing_status = ProcessingStatus.FAILED_RETRYABLE
            metadata = dict(ticket.ticket_metadata or {})
            metadata["last_dlq_error"] = error_reason
            ticket.ticket_metadata = metadata
            db.add(ticket)
            await db.commit()

    return {
        "ticket_id": str(ticket_id),
        "status": ProcessingStatus.FAILED_RETRYABLE.value,
        "error_reason": error_reason,
    }


@celery_app.task(
    name="app.worker.tasks.handle_ai_evaluation_dlq_task",
    queue=AI_EVALUATION_DLQ_NAME,
)
def handle_ai_evaluation_dlq_task(
    ticket_id: str,
    error_reason: str,
) -> Dict[str, Any]:
    """Dead-Letter Queue (`ai_evaluation_dlq`) handler marking tickets as `FAILED_RETRYABLE`."""
    return _run_async(
        _mark_ticket_failed_retryable_async(
            ticket_id=ticket_id,
            error_reason=error_reason,
        )
    )

