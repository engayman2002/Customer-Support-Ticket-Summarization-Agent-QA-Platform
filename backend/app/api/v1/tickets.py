from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedUser, require_roles
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.ticket import Ticket
from app.services.evaluation_service import evaluate_and_persist_ticket

router = APIRouter(prefix="/api/v1/tickets", tags=["Tickets & AI QA Evaluation"])


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
    existing_ticket = (
        await db.execute(existing_stmt)
    ).scalar_one_or_none()
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

