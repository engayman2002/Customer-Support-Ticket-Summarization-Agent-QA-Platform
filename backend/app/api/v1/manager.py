from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import AuthenticatedUser, require_roles
from app.db.session import get_db
from app.models.ai_qa_report import AiQaReport
from app.models.enums import UserRole
from app.models.ticket import Ticket
from app.models.user import User

router = APIRouter(prefix="/api/v1/manager", tags=["Manager Analytics"])


def _parse_optional_iso(raw_dt: Optional[str]) -> Optional[datetime]:
    if not raw_dt or not raw_dt.strip():
        return None
    cleaned = raw_dt.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


@router.get(
    "/analytics/overview",
    summary="Aggregate team KPIs, daily score trend, issue category breakdown, and risk matrix",
)
async def get_manager_analytics_overview(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    team_id: Optional[str] = Query(default=None, alias="teamId"),
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.MANAGER, UserRole.ADMIN)
    ),
) -> Dict[str, Any]:
    """
    Section 5.2: `GET /api/v1/manager/analytics/overview`
    - Protected: `MANAGER`, `ADMIN`.
    - Computes aggregated KPIs (`total_tickets_evaluated`, `average_agent_score`,
      `proper_resolution_rate_pct`, `premature_closure_rate_pct`, `avg_empathy_rating`,
      `unreviewed_low_score_tickets_count`), `score_trend_daily`, `issue_category_breakdown`,
      and `agent_risk_matrix`.
    """
    stmt = (
        select(Ticket)
        .join(AiQaReport, AiQaReport.ticket_id == Ticket.id)
        .options(
            selectinload(Ticket.ai_qa_report),
            selectinload(Ticket.assigned_agent),
            selectinload(Ticket.manager_feedbacks),
        )
    )

    parsed_from = _parse_optional_iso(from_date)
    parsed_to = _parse_optional_iso(to_date)

    if parsed_from is not None:
        stmt = stmt.where(Ticket.ticket_closed_at >= parsed_from)
    if parsed_to is not None:
        stmt = stmt.where(Ticket.ticket_closed_at <= parsed_to)

    if team_id and team_id.strip().lower() not in {"all", ""}:
        try:
            manager_uuid = uuid.UUID(team_id.strip())
            stmt = stmt.join(User, Ticket.assigned_agent_id == User.id).where(
                User.manager_id == manager_uuid
            )
        except ValueError:
            pass

    result = await db.execute(stmt)
    tickets = list(result.scalars().unique().all())

    total_evaluated = len(tickets)
    if total_evaluated == 0:
        return {
            "kpis": {
                "total_tickets_evaluated": 0,
                "average_agent_score": 0.0,
                "proper_resolution_rate_pct": 0.0,
                "premature_closure_rate_pct": 0.0,
                "avg_empathy_rating": 0.0,
                "unreviewed_low_score_tickets_count": 0,
            },
            "score_trend_daily": [],
            "issue_category_breakdown": [],
            "agent_risk_matrix": [],
        }

    total_score = 0
    proper_resolutions = 0
    premature_closures = 0
    total_empathy = 0
    unreviewed_low_score = 0

    daily_buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"score_sum": 0, "premature_closures": 0, "total_tickets": 0}
    )
    category_buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "score_sum": 0}
    )
    agent_buckets: Dict[str, Dict[str, Any]] = {}

    for tkt in tickets:
        report = tkt.ai_qa_report
        if report is None:
            continue

        score = int(report.agent_score)
        empathy = int(report.empathy_rating)
        is_proper = bool(report.is_resolved_properly)
        is_premature = bool(report.premature_closure_detected)

        total_score += score
        total_empathy += empathy
        if is_proper:
            proper_resolutions += 1
        if is_premature:
            premature_closures += 1

        if score < 60 and len(tkt.manager_feedbacks or []) == 0:
            unreviewed_low_score += 1

        day_key = (
            tkt.ticket_closed_at.strftime("%Y-%m-%d")
            if tkt.ticket_closed_at
            else "unknown"
        )
        daily_buckets[day_key]["score_sum"] += score
        daily_buckets[day_key]["total_tickets"] += 1
        if is_premature:
            daily_buckets[day_key]["premature_closures"] += 1

        cat_key = report.issue_category.value
        category_buckets[cat_key]["count"] += 1
        category_buckets[cat_key]["score_sum"] += score

        agent_id_str = str(tkt.assigned_agent_id)
        if agent_id_str not in agent_buckets:
            agent_buckets[agent_id_str] = {
                "agent_id": agent_id_str,
                "full_name": tkt.assigned_agent.full_name
                if tkt.assigned_agent
                else "Support Agent",
                "email": tkt.assigned_agent.email
                if tkt.assigned_agent
                else "",
                "total_tickets": 0,
                "score_sum": 0,
                "empathy_sum": 0,
                "premature_closures": 0,
                "proper_resolutions": 0,
            }
        ab = agent_buckets[agent_id_str]
        ab["total_tickets"] += 1
        ab["score_sum"] += score
        ab["empathy_sum"] += empathy
        if is_premature:
            ab["premature_closures"] += 1
        if is_proper:
            ab["proper_resolutions"] += 1

    score_trend_daily = [
        {
            "date": day,
            "avg_score": round(
                bucket["score_sum"] / bucket["total_tickets"], 1
            ),
            "premature_closures": bucket["premature_closures"],
            "total_tickets": bucket["total_tickets"],
        }
        for day, bucket in sorted(daily_buckets.items(), key=lambda x: x[0])
    ]

    issue_category_breakdown = [
        {
            "category": cat,
            "count": bucket["count"],
            "avg_score": round(bucket["score_sum"] / bucket["count"], 1),
        }
        for cat, bucket in sorted(
            category_buckets.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )
    ]

    agent_risk_matrix = [
        {
            "agent_id": ab["agent_id"],
            "full_name": ab["full_name"],
            "email": ab["email"],
            "evaluated_tickets": ab["total_tickets"],
            "average_agent_score": round(
                ab["score_sum"] / ab["total_tickets"], 1
            ),
            "proper_resolution_rate_pct": round(
                (ab["proper_resolutions"] / ab["total_tickets"]) * 100.0, 1
            ),
            "premature_closure_rate_pct": round(
                (ab["premature_closures"] / ab["total_tickets"]) * 100.0, 1
            ),
            "avg_empathy_rating": round(
                ab["empathy_sum"] / ab["total_tickets"], 1
            ),
        }
        for ab in agent_buckets.values()
    ]
    agent_risk_matrix.sort(
        key=lambda item: (
            -item["premature_closure_rate_pct"],
            item["average_agent_score"],
        )
    )

    return {
        "kpis": {
            "total_tickets_evaluated": total_evaluated,
            "average_agent_score": round(total_score / total_evaluated, 1),
            "proper_resolution_rate_pct": round(
                (proper_resolutions / total_evaluated) * 100.0, 1
            ),
            "premature_closure_rate_pct": round(
                (premature_closures / total_evaluated) * 100.0, 1
            ),
            "avg_empathy_rating": round(total_empathy / total_evaluated, 1),
            "unreviewed_low_score_tickets_count": unreviewed_low_score,
        },
        "score_trend_daily": score_trend_daily,
        "issue_category_breakdown": issue_category_breakdown,
        "agent_risk_matrix": agent_risk_matrix[:5],
    }


@router.get(
    "/agents/leaderboard",
    summary="Per-agent QA score averages, resolution rates, and premature closures",
)
async def get_manager_agents_leaderboard(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(
        require_roles(UserRole.MANAGER, UserRole.ADMIN)
    ),
) -> Dict[str, Any]:
    """Section 5.1: `GET /api/v1/manager/agents/leaderboard`."""
    overview = await get_manager_analytics_overview(
        from_date=None,
        to_date=None,
        team_id=None,
        db=db,
        current_user=current_user,
    )
    leaderboard = sorted(
        overview.get("agent_risk_matrix", []),
        key=lambda x: x["average_agent_score"],
        reverse=True,
    )
    return {"agents": leaderboard}

