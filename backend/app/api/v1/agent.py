from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.tickets import _format_iso_utc, _serialize_manager_feedback
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.models.ai_qa_report import AiQaReport
from app.models.enums import (
    CoachingPriority,
    FeedbackReadStatus,
    UserRole,
)
from app.models.manager_feedback import ManagerFeedback
from app.models.ticket import Ticket

router = APIRouter( tags=["Agent Workspace & Feedback Inbox"])


class UpdateFeedbackStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_status: FeedbackReadStatus
    completed_action_item_ids: Optional[List[str]] = None
    action_items: Optional[List[Dict[str, Any]]] = None
    agent_acknowledgement_note: Optional[str] = None


@router.get(
    "/api/v1/agent/me/summary",
    status_code=status.HTTP_200_OK,
    summary="Personal 30-day KPI summary, score trajectory, unread feedback count, and recent AI coaching",
)
async def get_agent_personal_summary(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Section 5.1 & 6.4: `GET /api/v1/agent/me/summary`
    - Returns personal KPI metrics (`total_tickets_evaluated`, `average_agent_score`,
      `proper_resolution_rate_pct`, `premature_closure_rate_pct`, `avg_empathy_rating`,
      `avg_clarity_rating`, `avg_ownership_rating`), `unread_feedback_count`,
      `high_priority_unread_count`, `score_trend_daily`, and `recent_coaching_plans`.
    """
    agent_uuid = uuid.UUID(str(current_user.id))

    ticket_stmt = (
        select(Ticket)
        .join(AiQaReport, AiQaReport.ticket_id == Ticket.id)
        .where(Ticket.assigned_agent_id == agent_uuid)
        .options(selectinload(Ticket.ai_qa_report))
        .order_by(desc(Ticket.ticket_closed_at))
    )
    tickets = list(
        (await db.execute(ticket_stmt)).scalars().unique().all()
    )

    fb_stmt = select(ManagerFeedback).where(
        ManagerFeedback.agent_id == agent_uuid
    )
    feedbacks = list((await db.execute(fb_stmt)).scalars().all())

    unread_count = sum(
        1 for fb in feedbacks if fb.read_status == FeedbackReadStatus.UNREAD
    )
    high_priority_unread_count = sum(
        1
        for fb in feedbacks
        if fb.read_status == FeedbackReadStatus.UNREAD
        and fb.coaching_priority
        in {CoachingPriority.HIGH, CoachingPriority.CRITICAL}
    )

    total_evaluated = len(tickets)
    if total_evaluated == 0:
        return {
            "agent": {
                "id": str(current_user.id),
                "email": current_user.email,
                "full_name": current_user.full_name,
            },
            "kpis": {
                "total_tickets_evaluated": 0,
                "average_agent_score": 0.0,
                "proper_resolution_rate_pct": 0.0,
                "premature_closure_rate_pct": 0.0,
                "avg_empathy_rating": 0.0,
                "avg_clarity_rating": 0.0,
                "avg_ownership_rating": 0.0,
                "unread_feedback_count": unread_count,
                "high_priority_unread_count": high_priority_unread_count,
            },
            "score_trend_daily": [],
            "recent_coaching_plans": [],
        }

    score_sum = 0
    proper_count = 0
    premature_count = 0
    empathy_sum = 0
    clarity_sum = 0
    ownership_sum = 0

    daily_buckets: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"score_sum": 0, "count": 0}
    )
    recent_coaching_plans: List[Dict[str, Any]] = []

    for tkt in tickets:
        rep = tkt.ai_qa_report
        if rep is None:
            continue

        score_sum += int(rep.agent_score)
        empathy_sum += int(rep.empathy_rating)
        clarity_sum += int(rep.clarity_and_accuracy_rating)
        ownership_sum += int(rep.ownership_and_efficiency_rating)
        if rep.is_resolved_properly:
            proper_count += 1
        if rep.premature_closure_detected:
            premature_count += 1

        day_key = (
            tkt.ticket_closed_at.strftime("%Y-%m-%d")
            if tkt.ticket_closed_at
            else "unknown"
        )
        daily_buckets[day_key]["score_sum"] += int(rep.agent_score)
        daily_buckets[day_key]["count"] += 1

        if len(recent_coaching_plans) < 10:
            recent_coaching_plans.append(
                {
                    "ticket_id": str(tkt.id),
                    "external_ticket_id": tkt.external_ticket_id,
                    "subject": tkt.subject,
                    "ticket_closed_at": _format_iso_utc(tkt.ticket_closed_at),
                    "agent_score": rep.agent_score,
                    "resolution_status": rep.resolution_status.value,
                    "issue_category": rep.issue_category.value,
                    "strengths": list(rep.strengths or []),
                    "areas_for_improvement": list(
                        rep.areas_for_improvement or []
                    ),
                    "actionable_coaching_plan": list(
                        rep.actionable_coaching_plan or []
                    ),
                }
            )

    score_trend_daily = [
        {
            "date": day,
            "avg_score": round(b["score_sum"] / b["count"], 1),
            "total_tickets": b["count"],
        }
        for day, b in sorted(daily_buckets.items(), key=lambda x: x[0])
    ]

    return {
        "agent": {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
        },
        "kpis": {
            "total_tickets_evaluated": total_evaluated,
            "average_agent_score": round(score_sum / total_evaluated, 1),
            "proper_resolution_rate_pct": round(
                (proper_count / total_evaluated) * 100.0, 1
            ),
            "premature_closure_rate_pct": round(
                (premature_count / total_evaluated) * 100.0, 1
            ),
            "avg_empathy_rating": round(empathy_sum / total_evaluated, 1),
            "avg_clarity_rating": round(clarity_sum / total_evaluated, 1),
            "avg_ownership_rating": round(ownership_sum / total_evaluated, 1),
            "unread_feedback_count": unread_count,
            "high_priority_unread_count": high_priority_unread_count,
        },
        "score_trend_daily": score_trend_daily,
        "recent_coaching_plans": recent_coaching_plans,
    }


@router.get(
    "/api/v1/agent/me/feedback",
    status_code=status.HTTP_200_OK,
    summary="Paginated inbox of manager instructions and coaching items assigned to current agent",
)
async def list_agent_feedback_inbox(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    read_status: Optional[FeedbackReadStatus] = Query(
        default=None, alias="readStatus"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Section 5.1 & 6.4: `GET /api/v1/agent/me/feedback`
    - Returns paginated list of `ManagerFeedback` items assigned to `current_user.id`.
    """
    agent_uuid = uuid.UUID(str(current_user.id))

    stmt = (
        select(ManagerFeedback)
        .where(ManagerFeedback.agent_id == agent_uuid)
        .options(
            selectinload(ManagerFeedback.manager),
            selectinload(ManagerFeedback.ticket).selectinload(
                Ticket.ai_qa_report
            ),
        )
        .order_by(desc(ManagerFeedback.created_at))
    )
    if read_status is not None:
        stmt = stmt.where(ManagerFeedback.read_status == read_status)

    all_feedbacks = list((await db.execute(stmt)).scalars().unique().all())
    total_records = len(all_feedbacks)
    total_pages = (
        max(1, math.ceil(total_records / limit)) if total_records > 0 else 1
    )
    offset = (page - 1) * limit
    page_items = all_feedbacks[offset : offset + limit]

    rows: List[Dict[str, Any]] = []
    for fb in page_items:
        serialized = _serialize_manager_feedback(fb)
        tkt = fb.ticket
        serialized["ticket"] = (
            {
                "ticket_id": str(tkt.id),
                "external_ticket_id": tkt.external_ticket_id,
                "subject": tkt.subject,
                "ticket_closed_at": _format_iso_utc(tkt.ticket_closed_at),
                "ai_agent_score": tkt.ai_qa_report.agent_score
                if tkt.ai_qa_report
                else None,
                "resolution_status": tkt.ai_qa_report.resolution_status.value
                if tkt.ai_qa_report
                else None,
            }
            if tkt
            else None
        )
        rows.append(serialized)

    return {
        "data": rows,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


@router.patch(
    "/api/v1/feedback/{feedback_id}/status",
    status_code=status.HTTP_200_OK,
    summary="Mark manager feedback as READ or ACKNOWLEDGED and update completed action items",
)
async def update_feedback_read_status(
    feedback_id: uuid.UUID,
    payload: UpdateFeedbackStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Section 5.2: `PATCH /api/v1/feedback/{feedbackId}/status`
    - Auth: `AGENT` matching `feedback.agent_id` (or `ADMIN`); returns `403 Forbidden`
      if another agent attempts to acknowledge someone else's feedback.
    - Updates `read_status` (`READ` or `ACKNOWLEDGED`), records `read_at` / `acknowledged_at`,
      updates `action_items` completion states, and saves `agent_acknowledgement_note`.
    """
    stmt = (
        select(ManagerFeedback)
        .where(ManagerFeedback.id == feedback_id)
        .options(selectinload(ManagerFeedback.manager))
    )
    feedback = (await db.execute(stmt)).scalar_one_or_none()
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feedback '{feedback_id}' not found.",
        )

    if str(feedback.agent_id) != str(
        current_user.id
    ) and current_user.role not in {UserRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned agent can update or acknowledge this feedback item.",
        )

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    feedback.read_status = payload.read_status

    if payload.read_status in {
        FeedbackReadStatus.READ,
        FeedbackReadStatus.ACKNOWLEDGED,
    }:
        if feedback.read_at is None:
            feedback.read_at = now_naive

    if payload.read_status == FeedbackReadStatus.ACKNOWLEDGED:
        feedback.acknowledged_at = now_naive

    if payload.agent_acknowledgement_note is not None:
        feedback.agent_acknowledgement_note = (
            payload.agent_acknowledgement_note.strip()
        )

    existing_items = [dict(item) for item in (feedback.action_items or [])]
    if payload.action_items is not None:
        feedback.action_items = [dict(item) for item in payload.action_items]
    elif payload.completed_action_item_ids is not None:
        completed_set = set(payload.completed_action_item_ids)
        for item in existing_items:
            if str(item.get("id")) in completed_set:
                item["completed"] = True
        feedback.action_items = existing_items

    feedback.updated_at = now_naive
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return _serialize_manager_feedback(feedback)

