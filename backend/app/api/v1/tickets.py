from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import AuthenticatedUser, get_current_user, require_roles
from app.db.session import get_db
from app.models.ai_qa_report import AiQaReport
from app.models.enums import (
    CoachingPriority,
    FeedbackReadStatus,
    ResolutionStatus,
    UserRole,
)
from app.models.manager_feedback import ManagerFeedback
from app.models.ticket import Ticket
from app.services.evaluation_service import evaluate_and_persist_ticket

router = APIRouter(prefix="/api/v1/tickets", tags=["Tickets & AI QA Evaluation"])


class FeedbackActionItemInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:6]}")
    description: str = Field(..., min_length=2)
    completed: bool = Field(default=False)


class CreateManagerFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager_override_score: Optional[int] = Field(default=None, ge=0, le=100)
    coaching_priority: CoachingPriority = Field(
        default=CoachingPriority.MEDIUM
    )
    comments: str = Field(..., min_length=3)
    action_items: List[FeedbackActionItemInput] = Field(default_factory=list)


def _format_iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).isoformat()
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _serialize_ai_qa_report(report: Optional[AiQaReport]) -> Optional[Dict[str, Any]]:
    if report is None:
        return None
    return {
        "id": str(report.id),
        "ticket_id": str(report.ticket_id),
        "summary": report.summary,
        "core_issue": report.core_issue,
        "issue_category": report.issue_category.value,
        "resolution_status": report.resolution_status.value,
        "is_resolved_properly": report.is_resolved_properly,
        "premature_closure_detected": report.premature_closure_detected,
        "premature_closure_reason": report.premature_closure_reason,
        "agent_score": report.agent_score,
        "empathy_rating": report.empathy_rating,
        "clarity_and_accuracy_rating": report.clarity_and_accuracy_rating,
        "ownership_and_efficiency_rating": report.ownership_and_efficiency_rating,
        "customer_sentiment_trajectory": report.customer_sentiment_trajectory.value,
        "strengths": list(report.strengths or []),
        "areas_for_improvement": list(report.areas_for_improvement or []),
        "flagged_evidence_quotes": list(report.flagged_evidence_quotes or []),
        "actionable_coaching_plan": list(report.actionable_coaching_plan or []),
        "model_used": report.model_used,
        "prompt_tokens": report.prompt_tokens,
        "completion_tokens": report.completion_tokens,
        "inference_latency_ms": report.inference_latency_ms,
        "evaluated_at": _format_iso_utc(report.evaluated_at),
    }


def _serialize_manager_feedback(fb: ManagerFeedback) -> Dict[str, Any]:
    return {
        "id": str(fb.id),
        "ticket_id": str(fb.ticket_id),
        "manager_id": str(fb.manager_id),
        "manager": {
            "id": str(fb.manager.id),
            "full_name": fb.manager.full_name,
            "email": fb.manager.email,
        }
        if fb.manager
        else None,
        "agent_id": str(fb.agent_id),
        "manager_override_score": fb.manager_override_score,
        "coaching_priority": fb.coaching_priority.value,
        "comments": fb.comments,
        "action_items": list(fb.action_items or []),
        "read_status": fb.read_status.value,
        "agent_acknowledgement_note": fb.agent_acknowledgement_note,
        "read_at": _format_iso_utc(fb.read_at),
        "acknowledged_at": _format_iso_utc(fb.acknowledged_at),
        "created_at": _format_iso_utc(fb.created_at),
        "updated_at": _format_iso_utc(fb.updated_at),
    }


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="Paginated, filterable list of tickets with AI QA summary and feedback status",
)
async def list_tickets_for_review(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    resolution_status: Optional[ResolutionStatus] = Query(
        default=None, alias="resolutionStatus"
    ),
    min_score: Optional[int] = Query(
        default=None, ge=0, le=100, alias="minScore"
    ),
    max_score: Optional[int] = Query(
        default=None, ge=0, le=100, alias="maxScore"
    ),
    premature_closure_only: Optional[bool] = Query(
        default=None, alias="prematureClosureOnly"
    ),
    pending_feedback_only: Optional[bool] = Query(
        default=None, alias="pendingFeedbackOnly"
    ),
    agent_id: Optional[uuid.UUID] = Query(default=None, alias="agentId"),
    search: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.MANAGER, UserRole.ADMIN)
    ),
) -> Dict[str, Any]:
    """
    Section 5.2: `GET /api/v1/tickets`
    - Protected: `MANAGER`, `ADMIN`.
    - Supports filtering by `resolutionStatus`, `minScore`, `maxScore`,
      `prematureClosureOnly`, `pendingFeedbackOnly`, `agentId`, and `search`.
    """
    stmt = (
        select(Ticket)
        .outerjoin(AiQaReport, AiQaReport.ticket_id == Ticket.id)
        .options(
            selectinload(Ticket.assigned_agent),
            selectinload(Ticket.ai_qa_report),
            selectinload(Ticket.manager_feedbacks),
        )
        .order_by(desc(Ticket.ticket_closed_at))
    )

    if agent_id is not None:
        stmt = stmt.where(Ticket.assigned_agent_id == agent_id)

    if search and search.strip():
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Ticket.external_ticket_id.ilike(q),
                Ticket.subject.ilike(q),
            )
        )

    if resolution_status is not None:
        stmt = stmt.where(AiQaReport.resolution_status == resolution_status)

    if min_score is not None:
        stmt = stmt.where(AiQaReport.agent_score >= min_score)

    if max_score is not None:
        stmt = stmt.where(AiQaReport.agent_score <= max_score)

    if premature_closure_only is True:
        stmt = stmt.where(AiQaReport.premature_closure_detected.is_(True))

    result = await db.execute(stmt)
    all_matching = list(result.scalars().unique().all())

    if pending_feedback_only is True:
        all_matching = [
            t for t in all_matching if len(t.manager_feedbacks or []) == 0
        ]

    total_records = len(all_matching)
    total_pages = max(1, math.ceil(total_records / limit)) if total_records > 0 else 1
    offset = (page - 1) * limit
    page_items = all_matching[offset : offset + limit]

    rows: List[Dict[str, Any]] = []
    for tkt in page_items:
        feedbacks = sorted(
            list(tkt.manager_feedbacks or []),
            key=lambda f: f.created_at or datetime.min,
            reverse=True,
        )
        feedback_status = (
            feedbacks[0].read_status.value if feedbacks else "NONE"
        )
        report = tkt.ai_qa_report

        rows.append(
            {
                "ticket_id": str(tkt.id),
                "external_ticket_id": tkt.external_ticket_id,
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
                else {
                    "id": str(tkt.assigned_agent_id),
                    "full_name": "Assigned Agent",
                    "email": "",
                },
                "ticket_closed_at": _format_iso_utc(tkt.ticket_closed_at),
                "ai_qa_summary": {
                    "agent_score": report.agent_score,
                    "resolution_status": report.resolution_status.value,
                    "is_resolved_properly": report.is_resolved_properly,
                    "premature_closure_detected": report.premature_closure_detected,
                    "empathy_rating": report.empathy_rating,
                    "issue_category": report.issue_category.value,
                    "customer_sentiment_trajectory": report.customer_sentiment_trajectory.value,
                }
                if report
                else None,
                "feedback_status": feedback_status,
            }
        )

    return {
        "data": rows,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


@router.get(
    "/{ticket_id}",
    status_code=status.HTTP_200_OK,
    summary="Detailed Ticket + Raw Transcript + AI QA Report + Manager Feedback History",
)
async def get_ticket_detail(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Section 5.1: `GET /api/v1/tickets/{id}`
    - Accessible to `MANAGER` and `ADMIN` for any ticket, or `AGENT` strictly when
      `ticket.assigned_agent_id == current_user.id`.
    """
    stmt = (
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.assigned_agent),
            selectinload(Ticket.ai_qa_report),
            selectinload(Ticket.manager_feedbacks).selectinload(
                ManagerFeedback.manager
            ),
        )
    )
    ticket = (await db.execute(stmt)).scalar_one_or_none()
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )

    if current_user.role == UserRole.AGENT and str(
        ticket.assigned_agent_id
    ) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agents can only view tickets assigned to themselves.",
        )

    feedbacks_sorted = sorted(
        list(ticket.manager_feedbacks or []),
        key=lambda f: f.created_at or datetime.min,
        reverse=True,
    )

    return {
        "ticket_id": str(ticket.id),
        "external_ticket_id": ticket.external_ticket_id,
        "integration_id": str(ticket.integration_id),
        "subject": ticket.subject,
        "channel": ticket.channel.value,
        "priority": ticket.priority.value,
        "processing_status": ticket.processing_status.value,
        "customer_identifier": ticket.customer_identifier,
        "first_response_time_seconds": ticket.first_response_time_seconds,
        "total_resolution_time_seconds": ticket.total_resolution_time_seconds,
        "ticket_created_at": _format_iso_utc(ticket.ticket_created_at),
        "ticket_closed_at": _format_iso_utc(ticket.ticket_closed_at),
        "assigned_agent": {
            "id": str(ticket.assigned_agent.id),
            "full_name": ticket.assigned_agent.full_name,
            "email": ticket.assigned_agent.email,
        }
        if ticket.assigned_agent
        else {
            "id": str(ticket.assigned_agent_id),
            "full_name": "Assigned Agent",
            "email": "",
        },
        "raw_transcript": list(ticket.raw_transcript or []),
        "ticket_metadata": dict(ticket.ticket_metadata or {}),
        "ai_qa_report": _serialize_ai_qa_report(ticket.ai_qa_report),
        "manager_feedbacks": [
            _serialize_manager_feedback(fb) for fb in feedbacks_sorted
        ],
    }


@router.post(
    "/{ticket_id}/feedback",
    status_code=status.HTTP_201_CREATED,
    summary="Submit manager evaluation, override score, and coaching instructions",
)
async def create_manager_feedback(
    ticket_id: uuid.UUID,
    payload: CreateManagerFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.MANAGER, UserRole.ADMIN)
    ),
) -> Dict[str, Any]:
    """
    Section 5.2: `POST /api/v1/tickets/{id}/feedback`
    - Protected: `MANAGER`, `ADMIN`.
    - Creates a `ManagerFeedback` record with `read_status = UNREAD` linked to the ticket and its assigned agent.
    """
    stmt = select(Ticket).where(Ticket.id == ticket_id)
    ticket = (await db.execute(stmt)).scalar_one_or_none()
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    feedback = ManagerFeedback(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        manager_id=uuid.UUID(str(current_user.id)),
        agent_id=ticket.assigned_agent_id,
        manager_override_score=payload.manager_override_score,
        coaching_priority=payload.coaching_priority,
        comments=payload.comments.strip(),
        action_items=[
            item.model_dump(mode="json") for item in payload.action_items
        ],
        read_status=FeedbackReadStatus.UNREAD,
        created_at=now_naive,
        updated_at=now_naive,
    )
    db.add(feedback)
    await db.commit()

    refreshed_stmt = (
        select(ManagerFeedback)
        .where(ManagerFeedback.id == feedback.id)
        .options(selectinload(ManagerFeedback.manager))
    )
    refreshed_fb = (await db.execute(refreshed_stmt)).scalar_one()
    return _serialize_manager_feedback(refreshed_fb)


@router.post(
    "/{ticket_id}/re-evaluate",
    status_code=status.HTTP_200_OK,
    summary="Re-run AI QA evaluation pipeline for a specific ticket (Manager/Admin)",
)
async def re_evaluate_ticket_endpoint(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.ADMIN, UserRole.MANAGER)
    ),
) -> Dict[str, Any]:
    """
    Section 5: `POST /api/v1/tickets/{ticket_id}/re-evaluate`
    - Accessible strictly to `ADMIN` and `MANAGER` roles (`403 Forbidden` for `AGENT`).
    - Re-runs the LangChain + `ChatGroq` evaluation pipeline, upserts `AiQaReport`,
      and returns the updated evaluation summary.
    """
    existing_stmt = select(Ticket).where(Ticket.id == ticket_id)
    existing_ticket = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing_ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )

    eval_summary = await evaluate_and_persist_ticket(
        ticket_id=ticket_id,
        db=db,
        bypass_rate_limit=True,
    )

    return {
        "status": eval_summary["status"],
        "ticket_id": eval_summary["ticket_id"],
        "external_ticket_id": eval_summary["external_ticket_id"],
        "report_id": eval_summary["report_id"],
        "processing_status": eval_summary["processing_status"],
        "agent_score": eval_summary["agent_score"],
        "resolution_status": eval_summary["resolution_status"],
        "is_resolved_properly": eval_summary["is_resolved_properly"],
        "premature_closure_detected": eval_summary[
            "premature_closure_detected"
        ],
        "model_used": eval_summary["model_used"],
        "triggered_by": current_user.email,
    }
