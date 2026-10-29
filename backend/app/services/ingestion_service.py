from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.registry import ProviderRegistry
from app.models.enums import ProcessingStatus, UserRole
from app.models.integration import Integration
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket_payload import StandardTicketPayload
from app.services.idempotency import (
    REDIS_AI_EVALUATION_QUEUE_KEY,
    push_job_to_redis_queue,
)


def _to_utc_naive(dt: datetime) -> datetime:
    """Convert timezone-aware or naive datetime to UTC naive datetime for PostgreSQL `TIMESTAMP`."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def resolve_or_provision_agent(
    db: AsyncSession,
    payload: StandardTicketPayload,
) -> User:
    """
    Resolve the assigned support `User` (`role = AGENT`) by `external_crm_agent_id`
    or `email`. If the CRM sends an unmapped agent, auto-provision an active `AGENT`
    record so webhook ingestion never drops a closed ticket.
    """
    normalized_email = payload.agent_email.strip().lower()
    stmt = select(User).where(
        or_(
            User.external_crm_agent_id == payload.external_agent_id,
            User.email == normalized_email,
        )
    )
    result = await db.execute(stmt)
    existing_user = result.scalars().first()

    if existing_user is not None:
        if not existing_user.external_crm_agent_id and payload.external_agent_id:
            existing_user.external_crm_agent_id = payload.external_agent_id
            await db.flush()
        return existing_user

    new_agent = User(
        id=uuid.uuid4(),
        email=normalized_email,
        password_hash="$2b$12$auto_provisioned_crm_agent_placeholder_hash",
        full_name=payload.agent_name or f"Agent {payload.external_agent_id}",
        role=UserRole.AGENT,
        external_crm_agent_id=payload.external_agent_id,
        is_active=True,
    )
    db.add(new_agent)
    await db.flush()
    return new_agent


async def ingest_normalized_ticket(
    db: AsyncSession,
    payload: StandardTicketPayload,
    *,
    enqueue_ai_eval: bool = True,
) -> Tuple[Ticket, bool]:
    """
    Idempotently persist a `StandardTicketPayload` into the `tickets` table with
    `processing_status = ProcessingStatus.QUEUED` and enqueue `ai_evaluation_queue`.
    Returns `(ticket, created_new)`.
    """
    created_at_naive = _to_utc_naive(payload.created_at)
    closed_at_naive = _to_utc_naive(payload.closed_at)

    existing_stmt = select(Ticket).where(
        Ticket.integration_id == payload.integration_id,
        Ticket.external_ticket_id == payload.external_ticket_id,
        Ticket.ticket_closed_at == closed_at_naive,
    )
    existing_result = await db.execute(existing_stmt)
    existing_ticket = existing_result.scalar_one_or_none()

    if existing_ticket is not None:
        return existing_ticket, False

    agent = await resolve_or_provision_agent(db, payload)

    serialized_transcript = [
        {
            "message_id": msg.message_id,
            "sender_role": msg.sender_role.value,
            "sender_name": msg.sender_name,
            "timestamp": msg.timestamp.astimezone(timezone.utc).isoformat()
            if msg.timestamp.tzinfo
            else msg.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "content": msg.content,
            "is_internal_note": msg.is_internal_note,
        }
        for msg in payload.messages
    ]

    ticket = Ticket(
        id=uuid.uuid4(),
        integration_id=payload.integration_id,
        external_ticket_id=payload.external_ticket_id,
        assigned_agent_id=agent.id,
        customer_identifier=payload.customer_identifier,
        subject=payload.subject,
        channel=payload.channel,
        priority=payload.priority,
        processing_status=ProcessingStatus.QUEUED,
        raw_transcript=serialized_transcript,
        ticket_metadata={
            "tags": payload.tags,
            "crm_provider": payload.crm_provider.value,
            "external_agent_id": payload.external_agent_id,
        },
        first_response_time_seconds=payload.first_response_time_seconds,
        total_resolution_time_seconds=payload.total_resolution_time_seconds,
        ticket_created_at=created_at_naive,
        ticket_closed_at=closed_at_naive,
    )

    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    if enqueue_ai_eval:
        await push_job_to_redis_queue(
            REDIS_AI_EVALUATION_QUEUE_KEY,
            {
                "task": "app.worker.tasks.evaluate_ticket_ai_qa_task",
                "ticket_id": str(ticket.id),
                "external_ticket_id": ticket.external_ticket_id,
                "enqueued_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return ticket, True


async def reconcile_integration_closed_tickets(
    db: AsyncSession,
    integration: Integration,
    *,
    backfill_payloads: Optional[
        List[Union[StandardTicketPayload, Dict[str, Any]]]
    ] = None,
    since_timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Section 2.4 Fallback Polling & Manual Sync Reconciler:
    1. Queries `connector.poll_closed_tickets(since_timestamp - 5m, integration)`.
    2. Normalizes any explicit `backfill_payloads` passed via manual sync API.
    3. Filters out already-persisted `(integration_id, external_ticket_id, ticket_closed_at)` tuples.
    4. Persists only missing or newly re-closed tickets with `processing_status = QUEUED`.
    5. Advances `integration.last_successful_sync_at`.
    """
    connector = ProviderRegistry.get_connector(integration.crm_type)
    base_since = (
        since_timestamp
        or integration.last_successful_sync_at
        or (datetime.now(timezone.utc) - timedelta(hours=24))
    )
    if base_since.tzinfo is None:
        base_since = base_since.replace(tzinfo=timezone.utc)
    overlap_since = base_since - timedelta(minutes=5)

    polled_items: List[StandardTicketPayload] = await connector.poll_closed_tickets(
        overlap_since, integration
    )

    candidate_payloads: List[StandardTicketPayload] = list(polled_items)
    if backfill_payloads:
        for item in backfill_payloads:
            if isinstance(item, StandardTicketPayload):
                candidate_payloads.append(item)
            elif isinstance(item, dict):
                normalized = connector.normalize_payload(item, integration.id)
                candidate_payloads.append(normalized)

    newly_ingested_ids: List[str] = []
    skipped_existing_count = 0

    for std_payload in candidate_payloads:
        ticket, created_new = await ingest_normalized_ticket(
            db, std_payload, enqueue_ai_eval=True
        )
        if created_new:
            newly_ingested_ids.append(str(ticket.id))
        else:
            skipped_existing_count += 1

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    integration.last_successful_sync_at = now_naive
    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    return {
        "integration_id": str(integration.id),
        "crm_type": integration.crm_type.value,
        "polled_count": len(candidate_payloads),
        "newly_ingested_count": len(newly_ingested_ids),
        "skipped_existing_count": skipped_existing_count,
        "ingested_ticket_ids": newly_ingested_ids,
        "last_successful_sync_at": integration.last_successful_sync_at.replace(
            tzinfo=timezone.utc
        ).isoformat(),
    }

