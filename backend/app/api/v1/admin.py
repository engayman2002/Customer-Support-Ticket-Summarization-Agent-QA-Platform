from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import AuthenticatedUser, require_roles
from app.db.session import get_db
from app.models.ai_qa_report import AiQaReport
from app.models.enums import ProcessingStatus, UserRole
from app.models.integration import Integration
from app.models.ticket import Ticket
from app.services.evaluation_service import (
    REDIS_AI_EVALUATION_DLQ_KEY,
    evaluate_and_persist_ticket,
)
from app.services.idempotency import (
    REDIS_AI_EVALUATION_QUEUE_KEY,
    get_redis_client,
)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin Telemetry, Integrations & DLQ Replay"],
)


def _compute_percentile(sorted_vals: List[int], percentile: float) -> float:
    """Compute nearest-rank / linear interpolated percentile from a sorted list of integers."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    pos = (percentile / 100.0) * (n - 1)
    lower_idx = int(math.floor(pos))
    upper_idx = int(math.ceil(pos))
    if lower_idx == upper_idx:
        return round(float(sorted_vals[lower_idx]), 1)
    weight = pos - lower_idx
    interpolated = (
        sorted_vals[lower_idx] * (1.0 - weight)
        + sorted_vals[upper_idx] * weight
    )
    return round(float(interpolated), 1)


def _format_iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).isoformat()
    return dt.replace(tzinfo=timezone.utc).isoformat()


async def _remove_ticket_from_redis_dlq(ticket_id_str: str) -> int:
    """Remove any DLQ envelope matching `ticket_id_str` from the Redis `ai_evaluation_dlq` list."""
    redis_client = get_redis_client()
    raw_items = await redis_client.lrange(REDIS_AI_EVALUATION_DLQ_KEY, 0, -1)
    removed_count = 0
    for raw in raw_items:
        try:
            parsed = json.loads(raw)
            if str(parsed.get("ticket_id")) == ticket_id_str:
                await redis_client.lrem(REDIS_AI_EVALUATION_DLQ_KEY, 0, raw)
                removed_count += 1
        except Exception:
            continue
    return removed_count


@router.get(
    "/telemetry",
    status_code=status.HTTP_200_OK,
    summary="Real-time AI observability telemetry, latency percentiles, token usage, and queue health",
)
async def get_admin_telemetry(
    db: AsyncSession = Depends(get_db),
    _current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
) -> Dict[str, Any]:
    """
    Section 1.3 & Phase 5: `GET /api/v1/admin/telemetry`
    - Protected: `ADMIN`, `MANAGER`.
    - Computes queue/processing status counts, `p50`/`p95`/`p99` inference latency (`ms`),
      prompt & completion token totals, fallback model invocation rate (`%`), and integration sync health.
    """
    tickets_stmt = select(Ticket).options(selectinload(Ticket.ai_qa_report))
    tickets = list((await db.execute(tickets_stmt)).scalars().unique().all())

    integrations_stmt = select(Integration)
    integrations = list((await db.execute(integrations_stmt)).scalars().all())

    status_counts: Dict[str, int] = {
        ProcessingStatus.QUEUED.value: 0,
        ProcessingStatus.PROCESSING.value: 0,
        ProcessingStatus.EVALUATED.value: 0,
        ProcessingStatus.FAILED_RETRYABLE.value: 0,
        ProcessingStatus.FAILED_PERMANENT.value: 0,
    }

    latencies: List[int] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reports = 0
    fallback_model_count = 0

    for tkt in tickets:
        st_key = tkt.processing_status.value
        status_counts[st_key] = status_counts.get(st_key, 0) + 1

        meta = tkt.ticket_metadata if isinstance(tkt.ticket_metadata, dict) else {}
        rep: Optional[AiQaReport] = tkt.ai_qa_report
        if rep is not None:
            total_reports += 1
            latencies.append(int(rep.inference_latency_ms))
            total_prompt_tokens += int(rep.prompt_tokens)
            total_completion_tokens += int(rep.completion_tokens)
            if (
                meta.get("fallback_model_used") is True
                or "fallback" in (rep.model_used or "").lower()
            ):
                fallback_model_count += 1

    sorted_latencies = sorted(latencies)
    avg_latency_ms = (
        round(sum(sorted_latencies) / len(sorted_latencies), 1)
        if sorted_latencies
        else 0.0
    )

    redis_client = get_redis_client()
    redis_dlq_len = int(await redis_client.llen(REDIS_AI_EVALUATION_DLQ_KEY))
    redis_eval_queue_len = int(
        await redis_client.llen(REDIS_AI_EVALUATION_QUEUE_KEY)
    )

    active_integrations = [i for i in integrations if i.is_active]
    sync_times = [
        i.last_successful_sync_at
        for i in integrations
        if i.last_successful_sync_at is not None
    ]
    latest_sync = max(sync_times) if sync_times else None

    fallback_rate_pct = (
        round((fallback_model_count / total_reports) * 100.0, 1)
        if total_reports > 0
        else 0.0
    )

    return {
        "queue_status": {
            "counts_by_status": status_counts,
            "total_tickets": len(tickets),
            "redis_dlq_length": redis_dlq_len,
            "redis_evaluation_queue_length": redis_eval_queue_len,
        },
        "latency_metrics": {
            "p50_latency_ms": _compute_percentile(sorted_latencies, 50.0),
            "p95_latency_ms": _compute_percentile(sorted_latencies, 95.0),
            "p99_latency_ms": _compute_percentile(sorted_latencies, 99.0),
            "avg_latency_ms": avg_latency_ms,
            "sample_size": len(sorted_latencies),
        },
        "token_and_model_telemetry": {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "total_reports": total_reports,
            "fallback_model_count": fallback_model_count,
            "fallback_rate_pct": fallback_rate_pct,
        },
        "integration_health": {
            "total_integrations": len(integrations),
            "active_integrations": len(active_integrations),
            "latest_sync_at": _format_iso_utc(latest_sync),
        },
    }


@router.get(
    "/dlq",
    status_code=status.HTTP_200_OK,
    summary="List failed tickets in FAILED_RETRYABLE / FAILED_PERMANENT state and Redis DLQ envelopes",
)
async def list_dlq_failed_tickets(
    db: AsyncSession = Depends(get_db),
    _current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
) -> Dict[str, Any]:
    """
    Phase 5: `GET /api/v1/admin/dlq`
    - Protected: `ADMIN`, `MANAGER`.
    - Returns failed tickets from PostgreSQL and recent failure envelopes from Redis `ai_evaluation_dlq`.
    """
    stmt = (
        select(Ticket)
        .where(
            Ticket.processing_status.in_(
                [
                    ProcessingStatus.FAILED_RETRYABLE,
                    ProcessingStatus.FAILED_PERMANENT,
                ]
            )
        )
        .options(selectinload(Ticket.assigned_agent))
        .order_by(desc(Ticket.updated_at))
    )
    failed_tickets = list((await db.execute(stmt)).scalars().unique().all())

    rows: List[Dict[str, Any]] = []
    for tkt in failed_tickets:
        meta = (
            dict(tkt.ticket_metadata)
            if isinstance(tkt.ticket_metadata, dict)
            else {}
        )
        rows.append(
            {
                "ticket_id": str(tkt.id),
                "external_ticket_id": tkt.external_ticket_id,
                "integration_id": str(tkt.integration_id),
                "subject": tkt.subject,
                "channel": tkt.channel.value,
                "priority": tkt.priority.value,
                "processing_status": tkt.processing_status.value,
                "assigned_agent": {
                    "id": str(tkt.assigned_agent.id),
                    "full_name": tkt.assigned_agent.full_name,
                    "email": tkt.assigned_agent.email,
                }
                if tkt.assigned_agent
                else None,
                "last_error": meta.get("last_dlq_error")
                or meta.get("last_error")
                or "AI evaluation failed after maximum retries.",
                "dlq_routed_at": meta.get("dlq_routed_at"),
                "ticket_closed_at": _format_iso_utc(tkt.ticket_closed_at),
                "updated_at": _format_iso_utc(tkt.updated_at),
            }
        )

    redis_client = get_redis_client()
    raw_envelopes = await redis_client.lrange(
        REDIS_AI_EVALUATION_DLQ_KEY, 0, 49
    )
    parsed_envelopes: List[Dict[str, Any]] = []
    for item in raw_envelopes:
        try:
            parsed_envelopes.append(json.loads(item))
        except Exception:
            continue

    return {
        "failed_tickets": rows,
        "total_failed": len(rows),
        "redis_dlq_envelopes": parsed_envelopes,
    }


@router.post(
    "/dlq/{ticket_id}/replay",
    status_code=status.HTTP_200_OK,
    summary="One-click DLQ Replay: re-run AI evaluation on a failed ticket and remove from DLQ",
)
async def replay_dlq_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
) -> Dict[str, Any]:
    """
    Phase 5: `POST /api/v1/admin/dlq/{ticket_id}/replay`
    - Protected: `ADMIN`, `MANAGER`.
    - Resets error metadata on the ticket, runs `evaluate_and_persist_ticket`,
      transitions `processing_status` to `EVALUATED`, and removes the ticket from Redis `ai_evaluation_dlq`.
    """
    stmt = select(Ticket).where(Ticket.id == ticket_id)
    ticket = (await db.execute(stmt)).scalar_one_or_none()
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )

    meta = (
        dict(ticket.ticket_metadata)
        if isinstance(ticket.ticket_metadata, dict)
        else {}
    )
    meta.pop("last_dlq_error", None)
    meta.pop("last_error", None)
    meta["last_replayed_at"] = datetime.now(timezone.utc).isoformat()
    meta["last_replayed_by"] = current_user.email
    ticket.ticket_metadata = meta
    db.add(ticket)
    await db.commit()

    eval_result = await evaluate_and_persist_ticket(
        ticket_id=ticket.id,
        db=db,
        bypass_rate_limit=True,
    )
    await _remove_ticket_from_redis_dlq(str(ticket.id))

    return {
        "status": "REPLAYED_AND_EVALUATED",
        "ticket_id": eval_result["ticket_id"],
        "external_ticket_id": eval_result["external_ticket_id"],
        "report_id": eval_result["report_id"],
        "processing_status": eval_result["processing_status"],
        "agent_score": eval_result["agent_score"],
        "resolution_status": eval_result["resolution_status"],
        "premature_closure_detected": eval_result[
            "premature_closure_detected"
        ],
        "model_used": eval_result["model_used"],
        "replayed_by": current_user.email,
    }


@router.post(
    "/dlq/replay-all",
    status_code=status.HTTP_200_OK,
    summary="Replay all tickets currently in FAILED_RETRYABLE state",
)
async def replay_all_dlq_tickets(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
) -> Dict[str, Any]:
    """
    Phase 5: `POST /api/v1/admin/dlq/replay-all`
    - Protected: `ADMIN`, `MANAGER`.
    - Replays all `FAILED_RETRYABLE` tickets and clears replayed items from Redis `ai_evaluation_dlq`.
    """
    stmt = select(Ticket).where(
        Ticket.processing_status == ProcessingStatus.FAILED_RETRYABLE
    )
    failed_tickets = list((await db.execute(stmt)).scalars().all())

    succeeded_ids: List[str] = []
    for tkt in failed_tickets:
        try:
            meta = (
                dict(tkt.ticket_metadata)
                if isinstance(tkt.ticket_metadata, dict)
                else {}
            )
            meta.pop("last_dlq_error", None)
            meta["last_replayed_at"] = datetime.now(timezone.utc).isoformat()
            meta["last_replayed_by"] = current_user.email
            tkt.ticket_metadata = meta
            db.add(tkt)
            await db.commit()

            await evaluate_and_persist_ticket(
                ticket_id=tkt.id,
                db=db,
                bypass_rate_limit=True,
            )
            await _remove_ticket_from_redis_dlq(str(tkt.id))
            succeeded_ids.append(str(tkt.id))
        except Exception:
            continue

    return {
        "status": "COMPLETED",
        "replayed_count": len(failed_tickets),
        "succeeded_count": len(succeeded_ids),
        "ticket_ids": succeeded_ids,
        "replayed_by": current_user.email,
    }

