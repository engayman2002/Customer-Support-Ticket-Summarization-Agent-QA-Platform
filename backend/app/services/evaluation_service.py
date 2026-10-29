from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_window import count_tokens, format_transcript_turns
from app.ai.evaluator import GroqTicketEvaluator
from app.ai.rate_limiter import acquire_groq_rate_limit
from app.db.session import AsyncSessionLocal
from app.models.ai_qa_report import AiQaReport
from app.models.enums import ProcessingStatus
from app.models.ticket import Ticket
from app.schemas.qa_evaluation import apply_qa_scoring_guardrails
from app.services.idempotency import (
    get_redis_client,
    push_job_to_redis_queue,
)

REDIS_QA_REPORT_READY_CHANNEL = "qa_report_ready"
REDIS_QA_REPORT_READY_HISTORY_KEY = "qa_report_ready:history"
REDIS_AI_EVALUATION_DLQ_KEY = "ai_evaluation_dlq"
COMPLETION_TOKEN_BUFFER = 1500


async def mark_ticket_failed_and_route_to_dlq(
    ticket_id: Union[str, uuid.UUID],
    error_reason: str,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Transition `Ticket.processing_status` to `ProcessingStatus.FAILED_RETRYABLE`,
    record `last_dlq_error` in `Ticket.ticket_metadata`, and push a failure envelope
    onto `ai_evaluation_dlq`.
    """
    target_uuid = (
        ticket_id
        if isinstance(ticket_id, uuid.UUID)
        else uuid.UUID(str(ticket_id))
    )

    async def _update_in_session(session: AsyncSession) -> None:
        stmt = select(Ticket).where(Ticket.id == target_uuid)
        result = await session.execute(stmt)
        ticket = result.scalar_one_or_none()
        if ticket is not None:
            ticket.processing_status = ProcessingStatus.FAILED_RETRYABLE
            metadata = dict(ticket.ticket_metadata or {})
            metadata["last_dlq_error"] = str(error_reason)
            metadata["dlq_routed_at"] = datetime.now(timezone.utc).isoformat()
            ticket.ticket_metadata = metadata
            session.add(ticket)
            await session.commit()

    if db is not None:
        await _update_in_session(db)
    else:
        async with AsyncSessionLocal() as session:
            await _update_in_session(session)

    dlq_envelope = {
        "task": "app.worker.tasks.handle_ai_evaluation_dlq_task",
        "ticket_id": str(target_uuid),
        "status": ProcessingStatus.FAILED_RETRYABLE.value,
        "error_reason": str(error_reason),
        "routed_at": datetime.now(timezone.utc).isoformat(),
    }
    await push_job_to_redis_queue(REDIS_AI_EVALUATION_DLQ_KEY, dlq_envelope)
    return dlq_envelope


async def _evaluate_and_persist_with_session(
    db: AsyncSession,
    target_uuid: uuid.UUID,
    evaluator: GroqTicketEvaluator,
    *,
    rate_limit_scope: str,
    rpm_limit: Optional[int],
    tpm_limit: Optional[int],
    bypass_rate_limit: bool,
    estimated_tokens_override: Optional[int],
    route_to_dlq_on_failure: bool,
    raise_on_failure: bool,
) -> Dict[str, Any]:
    stmt = select(Ticket).where(Ticket.id == target_uuid)
    result = await db.execute(stmt)
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise LookupError(f"Ticket '{target_uuid}' not found.")

    raw_turns = (
        list(ticket.raw_transcript)
        if isinstance(ticket.raw_transcript, list)
        else []
    )
    formatted_preview = format_transcript_turns(raw_turns, start_turn_number=1)
    estimated_tokens = (
        estimated_tokens_override
        if estimated_tokens_override is not None
        else (count_tokens(formatted_preview) + COMPLETION_TOKEN_BUFFER)
    )

    if not bypass_rate_limit:
        allowed, retry_after = await acquire_groq_rate_limit(
            estimated_tokens=estimated_tokens,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            scope=rate_limit_scope,
        )
        if not allowed:
            return {
                "status": "RATE_LIMITED",
                "ticket_id": str(ticket.id),
                "external_ticket_id": ticket.external_ticket_id,
                "processing_status": ticket.processing_status.value,
                "retry_after_seconds": retry_after,
            }

    # Transition ticket to PROCESSING
    ticket.processing_status = ProcessingStatus.PROCESSING
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    ticket_meta_payload: Dict[str, Any] = {
        "ticket_id": str(ticket.id),
        "external_ticket_id": ticket.external_ticket_id,
        "subject": ticket.subject,
        "channel": ticket.channel.value,
        "priority": ticket.priority.value,
        "first_response_time_seconds": ticket.first_response_time_seconds,
        "total_resolution_time_seconds": ticket.total_resolution_time_seconds,
        "created_at": ticket.ticket_created_at.replace(
            tzinfo=timezone.utc
        ).isoformat()
        if ticket.ticket_created_at
        else None,
        "closed_at": ticket.ticket_closed_at.replace(
            tzinfo=timezone.utc
        ).isoformat()
        if ticket.ticket_closed_at
        else None,
    }

    try:
        exec_result = await evaluator.evaluate_ticket(
            ticket_metadata=ticket_meta_payload,
            raw_transcript=raw_turns,
        )
        guarded_eval = apply_qa_scoring_guardrails(exec_result.evaluation)
    except Exception as exc:
        if route_to_dlq_on_failure:
            dlq_info = await mark_ticket_failed_and_route_to_dlq(
                ticket_id=ticket.id,
                error_reason=str(exc),
                db=db,
            )
            if not raise_on_failure:
                return dlq_info
        raise

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    existing_report_stmt = select(AiQaReport).where(
        AiQaReport.ticket_id == ticket.id
    )
    existing_report = (
        await db.execute(existing_report_stmt)
    ).scalar_one_or_none()

    serialized_quotes = [
        q.model_dump(mode="json") for q in guarded_eval.flagged_evidence_quotes
    ]
    serialized_coaching = [
        c.model_dump(mode="json") for c in guarded_eval.actionable_coaching_plan
    ]

    if existing_report is not None:
        report = existing_report
        report.summary = guarded_eval.summary
        report.core_issue = guarded_eval.core_issue
        report.issue_category = guarded_eval.issue_category
        report.resolution_status = guarded_eval.resolution_status
        report.is_resolved_properly = guarded_eval.is_resolved_properly
        report.premature_closure_detected = (
            guarded_eval.premature_closure_detected
        )
        report.premature_closure_reason = guarded_eval.premature_closure_reason
        report.agent_score = guarded_eval.agent_score
        report.empathy_rating = guarded_eval.empathy_rating
        report.clarity_and_accuracy_rating = (
            guarded_eval.clarity_and_accuracy_rating
        )
        report.ownership_and_efficiency_rating = (
            guarded_eval.ownership_and_efficiency_rating
        )
        report.customer_sentiment_trajectory = (
            guarded_eval.customer_sentiment_trajectory
        )
        report.strengths = list(guarded_eval.strengths)
        report.areas_for_improvement = list(guarded_eval.areas_for_improvement)
        report.flagged_evidence_quotes = serialized_quotes
        report.actionable_coaching_plan = serialized_coaching
        report.model_used = exec_result.model_used
        report.prompt_tokens = exec_result.prompt_tokens
        report.completion_tokens = exec_result.completion_tokens
        report.inference_latency_ms = exec_result.inference_latency_ms
        report.evaluated_at = now_naive
    else:
        report = AiQaReport(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            summary=guarded_eval.summary,
            core_issue=guarded_eval.core_issue,
            issue_category=guarded_eval.issue_category,
            resolution_status=guarded_eval.resolution_status,
            is_resolved_properly=guarded_eval.is_resolved_properly,
            premature_closure_detected=guarded_eval.premature_closure_detected,
            premature_closure_reason=guarded_eval.premature_closure_reason,
            agent_score=guarded_eval.agent_score,
            empathy_rating=guarded_eval.empathy_rating,
            clarity_and_accuracy_rating=guarded_eval.clarity_and_accuracy_rating,
            ownership_and_efficiency_rating=guarded_eval.ownership_and_efficiency_rating,
            customer_sentiment_trajectory=guarded_eval.customer_sentiment_trajectory,
            strengths=list(guarded_eval.strengths),
            areas_for_improvement=list(guarded_eval.areas_for_improvement),
            flagged_evidence_quotes=serialized_quotes,
            actionable_coaching_plan=serialized_coaching,
            model_used=exec_result.model_used,
            prompt_tokens=exec_result.prompt_tokens,
            completion_tokens=exec_result.completion_tokens,
            inference_latency_ms=exec_result.inference_latency_ms,
            evaluated_at=now_naive,
        )
        db.add(report)

    ticket.processing_status = ProcessingStatus.EVALUATED
    updated_meta = dict(ticket.ticket_metadata or {})
    updated_meta["fallback_model_used"] = exec_result.fallback_model_used
    updated_meta["was_compressed"] = exec_result.was_compressed
    updated_meta["model_used"] = exec_result.model_used
    ticket.ticket_metadata = updated_meta
    db.add(ticket)

    await db.commit()
    await db.refresh(report)
    await db.refresh(ticket)

    event_payload = {
        "ticket_id": str(ticket.id),
        "external_ticket_id": ticket.external_ticket_id,
        "report_id": str(report.id),
        "agent_score": report.agent_score,
        "resolution_status": report.resolution_status.value,
        "is_resolved_properly": report.is_resolved_properly,
        "premature_closure_detected": report.premature_closure_detected,
        "model_used": report.model_used,
        "fallback_model_used": exec_result.fallback_model_used,
    }
    serialized_event = json.dumps(event_payload)
    redis_client = get_redis_client()
    await redis_client.publish(REDIS_QA_REPORT_READY_CHANNEL, serialized_event)
    await redis_client.lpush(
        REDIS_QA_REPORT_READY_HISTORY_KEY, serialized_event
    )
    await redis_client.ltrim(REDIS_QA_REPORT_READY_HISTORY_KEY, 0, 199)

    return {
        "status": "EVALUATED",
        "ticket_id": str(ticket.id),
        "external_ticket_id": ticket.external_ticket_id,
        "report_id": str(report.id),
        "processing_status": ticket.processing_status.value,
        "agent_score": report.agent_score,
        "resolution_status": report.resolution_status.value,
        "is_resolved_properly": report.is_resolved_properly,
        "premature_closure_detected": report.premature_closure_detected,
        "model_used": report.model_used,
        "fallback_model_used": exec_result.fallback_model_used,
        "was_compressed": exec_result.was_compressed,
        "prompt_tokens": report.prompt_tokens,
        "completion_tokens": report.completion_tokens,
        "inference_latency_ms": report.inference_latency_ms,
    }


async def evaluate_and_persist_ticket(
    ticket_id: Union[str, uuid.UUID],
    db: Optional[AsyncSession] = None,
    evaluator: Optional[GroqTicketEvaluator] = None,
    *,
    rate_limit_scope: str = "default",
    rpm_limit: Optional[int] = None,
    tpm_limit: Optional[int] = None,
    bypass_rate_limit: bool = False,
    estimated_tokens_override: Optional[int] = None,
    route_to_dlq_on_failure: bool = True,
    raise_on_failure: bool = True,
) -> Dict[str, Any]:
    """
    End-to-end AI evaluation persistence service (Section 1.2 & 3.4):
    1. Acquires distributed Redis Lua RPM/TPM token budget (`acquire_groq_rate_limit`).
       If rate-limited, returns `{"status": "RATE_LIMITED", "retry_after_seconds": ...}`
       without blocking or dropping the ticket.
    2. Transitions `Ticket.processing_status` -> `PROCESSING`.
    3. Executes `GroqTicketEvaluator.evaluate_ticket` and applies `apply_qa_scoring_guardrails`.
    4. Atomically upserts `AiQaReport` and transitions `Ticket.processing_status` -> `EVALUATED`.
    5. Publishes completion notification to Redis channel `qa_report_ready`.
    """
    target_uuid = (
        ticket_id
        if isinstance(ticket_id, uuid.UUID)
        else uuid.UUID(str(ticket_id))
    )
    active_evaluator = evaluator or GroqTicketEvaluator()

    if db is not None:
        return await _evaluate_and_persist_with_session(
            db=db,
            target_uuid=target_uuid,
            evaluator=active_evaluator,
            rate_limit_scope=rate_limit_scope,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            bypass_rate_limit=bypass_rate_limit,
            estimated_tokens_override=estimated_tokens_override,
            route_to_dlq_on_failure=route_to_dlq_on_failure,
            raise_on_failure=raise_on_failure,
        )

    async with AsyncSessionLocal() as session:
        return await _evaluate_and_persist_with_session(
            db=session,
            target_uuid=target_uuid,
            evaluator=active_evaluator,
            rate_limit_scope=rate_limit_scope,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            bypass_rate_limit=bypass_rate_limit,
            estimated_tokens_override=estimated_tokens_override,
            route_to_dlq_on_failure=route_to_dlq_on_failure,
            raise_on_failure=raise_on_failure,
        )

