from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.ai.evaluator import GroqTicketEvaluator
from app.db.session import AsyncSessionLocal
from app.integrations.registry import ProviderRegistry
from app.models.enums import ProcessingStatus
from app.models.integration import Integration
from app.models.ticket import Ticket
from app.services.evaluation_service import (
    evaluate_and_persist_ticket,
    mark_ticket_failed_and_route_to_dlq,
)
from app.services.idempotency import (
    REDIS_AI_EVALUATION_QUEUE_KEY,
    push_job_to_redis_queue,
)
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


_LOOP_INGESTION_SEMAPHORES: Dict[int, asyncio.Semaphore] = {}


def _get_ingestion_semaphore() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    sem = _LOOP_INGESTION_SEMAPHORES.get(loop_id)
    if sem is None:
        sem = asyncio.Semaphore(12)
        _LOOP_INGESTION_SEMAPHORES[loop_id] = sem
    return sem


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
    await asyncio.sleep(0.08)
    semaphore = _get_ingestion_semaphore()
    async with semaphore:
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


async def evaluate_ticket_ai_qa_async(
    ticket_id: str,
    *,
    evaluator: Optional[GroqTicketEvaluator] = None,
    rate_limit_scope: str = "default",
    rpm_limit: Optional[int] = None,
    tpm_limit: Optional[int] = None,
    bypass_rate_limit: bool = False,
) -> Dict[str, Any]:
    """
    Async implementation of `evaluate_ticket_ai_qa_task` on `ai_evaluation_queue`:
    - Acquires distributed RPM/TPM budget via `acquire_groq_rate_limit`.
    - If rate-limited (`status == RATE_LIMITED`), re-enqueues the job with countdown
      onto `ai_evaluation_queue` without dropping the ticket or blocking a worker thread.
    - If evaluation fails after primary + fallback retries, routes the ticket to
      `handle_ai_evaluation_dlq_task` (`ai_evaluation_dlq`) with `FAILED_RETRYABLE`.
    """
    try:
        result = await evaluate_and_persist_ticket(
            ticket_id=ticket_id,
            evaluator=evaluator,
            rate_limit_scope=rate_limit_scope,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            bypass_rate_limit=bypass_rate_limit,
            route_to_dlq_on_failure=True,
            raise_on_failure=True,
        )
        if result.get("status") == "RATE_LIMITED":
            retry_after = float(result.get("retry_after_seconds", 2.0))
            await push_job_to_redis_queue(
                REDIS_AI_EVALUATION_QUEUE_KEY,
                {
                    "task": "app.worker.tasks.evaluate_ticket_ai_qa_task",
                    "ticket_id": str(ticket_id),
                    "status": "DEFERRED_RATE_LIMITED",
                    "countdown_seconds": retry_after,
                    "rescheduled_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return result
    except Exception as exc:
        dlq_result = await mark_ticket_failed_and_route_to_dlq(
            ticket_id=ticket_id,
            error_reason=str(exc),
        )
        return dlq_result


@celery_app.task(
    name="app.worker.tasks.evaluate_ticket_ai_qa_task",
    queue=AI_EVALUATION_QUEUE_NAME,
    bind=True,
    max_retries=4,
)
def evaluate_ticket_ai_qa_task(
    self: Any,
    ticket_id: str,
) -> Dict[str, Any]:
    """
    Rate-limited AI evaluation worker task on `ai_evaluation_queue`.
    Executes the LangChain + `ChatGroq` (`llama-3.3-70b-versatile` -> `llama-3.1-8b-instant`)
    structured evaluation pipeline and persists `AiQaReport`.
    """
    return _run_async(evaluate_ticket_ai_qa_async(ticket_id=ticket_id))


async def _mark_ticket_failed_retryable_async(
    ticket_id: str,
    error_reason: str,
) -> Dict[str, Any]:
    return await mark_ticket_failed_and_route_to_dlq(
        ticket_id=ticket_id,
        error_reason=error_reason,
    )


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
