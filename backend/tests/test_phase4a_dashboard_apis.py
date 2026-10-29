from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models import (
    AiQaReport,
    IssueCategory,
    ManagerFeedback,
    ProcessingStatus,
    ResolutionStatus,
    SentimentTrajectory,
    Ticket,
    TicketChannel,
    TicketPriority,
    UserRole,
)

SEEDED_ZENDESK_INTEGRATION_ID = uuid.UUID(
    "22222222-2222-4222-8222-222222222201"
)
SEEDED_ADMIN_ID = "11111111-1111-4111-8111-111111111101"
SEEDED_MANAGER_ID = "11111111-1111-4111-8111-111111111102"
SEEDED_SARAH_AGENT_ID = "11111111-1111-4111-8111-111111111103"
SEEDED_OMAR_AGENT_ID = "11111111-1111-4111-8111-111111111104"


async def _seed_evaluated_ticket(
    *,
    external_prefix: str,
    subject: str,
    agent_id: str,
    closed_at_naive: datetime,
    agent_score: int,
    empathy_rating: int,
    resolution_status: ResolutionStatus,
    is_resolved_properly: bool,
    premature_closure_detected: bool,
    issue_category: IssueCategory,
) -> Tuple[Ticket, AiQaReport]:
    tkt_id = uuid.uuid4()
    rep_id = uuid.uuid4()
    ticket = Ticket(
        id=tkt_id,
        integration_id=SEEDED_ZENDESK_INTEGRATION_ID,
        external_ticket_id=f"{external_prefix}-{uuid.uuid4().hex[:6]}",
        assigned_agent_id=uuid.UUID(agent_id),
        customer_identifier="cust_hash_phase4a",
        subject=subject,
        channel=TicketChannel.EMAIL,
        priority=TicketPriority.HIGH,
        processing_status=ProcessingStatus.EVALUATED,
        raw_transcript=[
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-28T10:00:00Z",
                "content": f"Customer question about {subject}",
            },
            {
                "sender_role": "AGENT",
                "timestamp": "2026-10-28T10:15:00Z",
                "content": "Agent response in transcript.",
            },
        ],
        ticket_metadata={"source": "phase4a_test"},
        first_response_time_seconds=180,
        total_resolution_time_seconds=900,
        ticket_created_at=closed_at_naive,
        ticket_closed_at=closed_at_naive,
    )
    report = AiQaReport(
        id=rep_id,
        ticket_id=tkt_id,
        summary=f"Executive summary for {subject} with complete evaluation details.",
        core_issue=f"Core issue for {subject}",
        issue_category=issue_category,
        resolution_status=resolution_status,
        is_resolved_properly=is_resolved_properly,
        premature_closure_detected=premature_closure_detected,
        premature_closure_reason=(
            "Closed before confirming customer fix worked."
            if premature_closure_detected
            else None
        ),
        agent_score=agent_score,
        empathy_rating=empathy_rating,
        clarity_and_accuracy_rating=8,
        ownership_and_efficiency_rating=8,
        customer_sentiment_trajectory=(
            SentimentTrajectory.UNCHANGED_NEGATIVE
            if premature_closure_detected
            else SentimentTrajectory.IMPROVED
        ),
        strengths=["Fast initial response"],
        areas_for_improvement=["Confirm resolution before closing"],
        flagged_evidence_quotes=(
            [
                {
                    "speaker": "AGENT",
                    "quote": "Agent response in transcript.",
                    "issue_type": "PREMATURE_CLOSURE",
                }
            ]
            if premature_closure_detected
            else []
        ),
        actionable_coaching_plan=[
            {
                "focus_area": "Resolution Confirmation",
                "specific_action": "Ask customer to confirm fix before closing.",
                "suggested_phrasing_example": "Please let me know if that resolves the issue on your end!",
            }
        ],
        model_used="llama-3.3-70b-versatile",
        prompt_tokens=420,
        completion_tokens=210,
        inference_latency_ms=340,
        evaluated_at=closed_at_naive,
    )

    async with AsyncSessionLocal() as db:
        db.add(ticket)
        db.add(report)
        await db.commit()
    return ticket, report


async def _cleanup_tickets(ticket_ids: List[uuid.UUID]) -> None:
    if not ticket_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ManagerFeedback).where(
                ManagerFeedback.ticket_id.in_(ticket_ids)
            )
        )
        await db.execute(
            delete(AiQaReport).where(AiQaReport.ticket_id.in_(ticket_ids))
        )
        await db.execute(delete(Ticket).where(Ticket.id.in_(ticket_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_manager_analytics_overview_kpis_trends_and_rbac() -> None:
    """
    Step 2.1: Verify `GET /api/v1/manager/analytics/overview` computes accurate
    averages, proper resolution rate, premature closure rate, daily score trend,
    and issue category breakdown, while rejecting `AGENT` tokens with `403 Forbidden`.
    """
    manager_token = create_access_token(
        sub=SEEDED_MANAGER_ID,
        email="manager@qa-platform.local",
        role=UserRole.MANAGER,
    )
    agent_token = create_access_token(
        sub=SEEDED_SARAH_AGENT_ID,
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT,
    )

    # Use a distinct future date window (2026-11-15 & 2026-11-16) to isolate KPI math from seed data
    day1 = datetime(2026, 11, 15, 12, 0, 0)
    day2 = datetime(2026, 11, 16, 14, 0, 0)

    t1, _ = await _seed_evaluated_ticket(
        external_prefix="ZD-P4A-KPI1",
        subject="Billing refund verified",
        agent_id=SEEDED_SARAH_AGENT_ID,
        closed_at_naive=day1,
        agent_score=90,
        empathy_rating=9,
        resolution_status=ResolutionStatus.RESOLVED,
        is_resolved_properly=True,
        premature_closure_detected=False,
        issue_category=IssueCategory.BILLING,
    )
    t2, _ = await _seed_evaluated_ticket(
        external_prefix="ZD-P4A-KPI2",
        subject="Webhook 500 error premature closure",
        agent_id=SEEDED_OMAR_AGENT_ID,
        closed_at_naive=day2,
        agent_score=40,
        empathy_rating=5,
        resolution_status=ResolutionStatus.PREMATURELY_CLOSED,
        is_resolved_properly=False,
        premature_closure_detected=True,
        issue_category=IssueCategory.TECHNICAL_BUG,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            # 1. AGENT token -> 403 Forbidden
            forbidden_res = await client.get(
                "/api/v1/manager/analytics/overview",
                headers={"Authorization": f"Bearer {agent_token}"},
            )
            assert forbidden_res.status_code == 403

            # 2. MANAGER token scoped to 2026-11-15..2026-11-16 -> exact math verification
            res = await client.get(
                "/api/v1/manager/analytics/overview",
                params={
                    "from": "2026-11-15T00:00:00Z",
                    "to": "2026-11-16T23:59:59Z",
                },
                headers={"Authorization": f"Bearer {manager_token}"},
            )
            assert res.status_code == 200
            data = res.json()

            kpis = data["kpis"]
            assert kpis["total_tickets_evaluated"] == 2
            assert kpis["average_agent_score"] == 65.0  # (90 + 40) / 2
            assert kpis["proper_resolution_rate_pct"] == 50.0
            assert kpis["premature_closure_rate_pct"] == 50.0
            assert kpis["avg_empathy_rating"] == 7.0  # (9 + 5) / 2
            assert kpis["unreviewed_low_score_tickets_count"] == 1

            trends = data["score_trend_daily"]
            assert len(trends) == 2
            assert trends[0]["date"] == "2026-11-15"
            assert trends[0]["avg_score"] == 90.0
            assert trends[0]["premature_closures"] == 0
            assert trends[1]["date"] == "2026-11-16"
            assert trends[1]["avg_score"] == 40.0
            assert trends[1]["premature_closures"] == 1

            categories = {
                c["category"]: c for c in data["issue_category_breakdown"]
            }
            assert "BILLING" in categories
            assert categories["BILLING"]["avg_score"] == 90.0
            assert "TECHNICAL_BUG" in categories
            assert categories["TECHNICAL_BUG"]["avg_score"] == 40.0
        finally:
            await _cleanup_tickets([t1.id, t2.id])


@pytest.mark.asyncio
async def test_tickets_review_list_filtering_pagination_and_detail_rbac() -> None:
    """
    Step 2.2: Verify `GET /api/v1/tickets` supports filtering by `resolutionStatus`,
    score ranges (`minScore`/`maxScore`), `agentId`, and `search` with pagination,
    and verify `GET /api/v1/tickets/{id}` enforces agent ownership RBAC.
    """
    manager_token = create_access_token(
        sub=SEEDED_MANAGER_ID,
        email="manager@qa-platform.local",
        role=UserRole.MANAGER,
    )
    sarah_token = create_access_token(
        sub=SEEDED_SARAH_AGENT_ID,
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT,
    )
    omar_token = create_access_token(
        sub=SEEDED_OMAR_AGENT_ID,
        email="omar.agent@qa-platform.local",
        role=UserRole.AGENT,
    )

    unique_tag = uuid.uuid4().hex[:6]
    closed_dt = datetime(2026, 11, 18, 10, 0, 0)

    t_high, _ = await _seed_evaluated_ticket(
        external_prefix=f"ZD-FILT-HI-{unique_tag}",
        subject=f"FilterTest High Score Resolved {unique_tag}",
        agent_id=SEEDED_SARAH_AGENT_ID,
        closed_at_naive=closed_dt,
        agent_score=95,
        empathy_rating=10,
        resolution_status=ResolutionStatus.RESOLVED,
        is_resolved_properly=True,
        premature_closure_detected=False,
        issue_category=IssueCategory.HOW_TO,
    )
    t_low, _ = await _seed_evaluated_ticket(
        external_prefix=f"ZD-FILT-LO-{unique_tag}",
        subject=f"FilterTest Premature Closure {unique_tag}",
        agent_id=SEEDED_OMAR_AGENT_ID,
        closed_at_naive=closed_dt,
        agent_score=38,
        empathy_rating=4,
        resolution_status=ResolutionStatus.PREMATURELY_CLOSED,
        is_resolved_properly=False,
        premature_closure_detected=True,
        issue_category=IssueCategory.TECHNICAL_BUG,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            # 1. Filter by resolutionStatus=PREMATURELY_CLOSED, maxScore=50, search=unique_tag
            res_premature = await client.get(
                "/api/v1/tickets",
                params={
                    "resolutionStatus": "PREMATURELY_CLOSED",
                    "maxScore": 50,
                    "search": unique_tag,
                    "page": 1,
                    "limit": 10,
                },
                headers={"Authorization": f"Bearer {manager_token}"},
            )
            assert res_premature.status_code == 200
            body_prem = res_premature.json()
            assert body_prem["pagination"]["total_records"] == 1
            assert body_prem["data"][0]["ticket_id"] == str(t_low.id)
            assert (
                body_prem["data"][0]["ai_qa_summary"]["resolution_status"]
                == "PREMATURELY_CLOSED"
            )
            assert body_prem["data"][0]["feedback_status"] == "NONE"

            # 2. Filter by agentId=Sarah and minScore=80
            res_sarah = await client.get(
                "/api/v1/tickets",
                params={
                    "agentId": SEEDED_SARAH_AGENT_ID,
                    "minScore": 80,
                    "search": unique_tag,
                },
                headers={"Authorization": f"Bearer {manager_token}"},
            )
            assert res_sarah.status_code == 200
            body_sarah = res_sarah.json()
            assert body_sarah["pagination"]["total_records"] == 1
            assert body_sarah["data"][0]["ticket_id"] == str(t_high.id)

            # 3. Detail endpoint RBAC: Sarah can view her own ticket (`t_high`) -> 200 OK
            own_detail_res = await client.get(
                f"/api/v1/tickets/{t_high.id}",
                headers={"Authorization": f"Bearer {sarah_token}"},
            )
            assert own_detail_res.status_code == 200
            assert own_detail_res.json()["ai_qa_report"]["agent_score"] == 95

            # 4. Detail endpoint RBAC: Omar cannot view Sarah's ticket (`t_high`) -> 403 Forbidden
            other_detail_res = await client.get(
                f"/api/v1/tickets/{t_high.id}",
                headers={"Authorization": f"Bearer {omar_token}"},
            )
            assert other_detail_res.status_code == 403
        finally:
            await _cleanup_tickets([t_high.id, t_low.id])


@pytest.mark.asyncio
async def test_submit_manager_feedback_and_agent_acknowledgement_workflow() -> None:
    """
    Step 2.3 & 2.4:
    1. Verify `POST /api/v1/tickets/{id}/feedback` creates unread manager feedback
       and blocks `AGENT` callers with `403 Forbidden`.
    2. Verify `GET /api/v1/agent/me/summary` and `GET /api/v1/agent/me/feedback` surface
       the new unread feedback item.
    3. Verify `PATCH /api/v1/feedback/{id}/status` allows the assigned agent (Sarah) to
       acknowledge the feedback and complete action items, while blocking another agent
       (Omar) with `403 Forbidden`.
    """
    manager_token = create_access_token(
        sub=SEEDED_MANAGER_ID,
        email="manager@qa-platform.local",
        role=UserRole.MANAGER,
    )
    sarah_token = create_access_token(
        sub=SEEDED_SARAH_AGENT_ID,
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT,
    )
    omar_token = create_access_token(
        sub=SEEDED_OMAR_AGENT_ID,
        email="omar.agent@qa-platform.local",
        role=UserRole.AGENT,
    )

    ticket, _ = await _seed_evaluated_ticket(
        external_prefix="ZD-P4A-FB",
        subject="API webhook failing with 403 error after key rotation",
        agent_id=SEEDED_SARAH_AGENT_ID,
        closed_at_naive=datetime(2026, 10, 29, 12, 0, 0),
        agent_score=42,
        empathy_rating=6,
        resolution_status=ResolutionStatus.PREMATURELY_CLOSED,
        is_resolved_properly=False,
        premature_closure_detected=True,
        issue_category=IssueCategory.TECHNICAL_BUG,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            feedback_payload: Dict[str, Any] = {
                "manager_override_score": 40,
                "coaching_priority": "HIGH",
                "comments": (
                    "Sarah, never close a technical blocker without confirming the customer's test succeeded."
                ),
                "action_items": [
                    {
                        "id": "act_1",
                        "description": "Re-open ticket and ask customer for failing request ID.",
                        "completed": False,
                    },
                    {
                        "id": "act_2",
                        "description": "Review the Webhook Troubleshooting Playbook.",
                        "completed": False,
                    },
                ],
            }

            # 1. AGENT cannot submit manager feedback -> 403 Forbidden
            agent_fb_res = await client.post(
                f"/api/v1/tickets/{ticket.id}/feedback",
                headers={"Authorization": f"Bearer {sarah_token}"},
                json=feedback_payload,
            )
            assert agent_fb_res.status_code == 403

            # 2. MANAGER submits feedback -> 201 Created with read_status = UNREAD
            create_fb_res = await client.post(
                f"/api/v1/tickets/{ticket.id}/feedback",
                headers={"Authorization": f"Bearer {manager_token}"},
                json=feedback_payload,
            )
            assert create_fb_res.status_code == 201
            fb_data = create_fb_res.json()
            feedback_id = fb_data["id"]
            assert fb_data["read_status"] == "UNREAD"
            assert fb_data["coaching_priority"] == "HIGH"
            assert fb_data["manager_override_score"] == 40
            assert len(fb_data["action_items"]) == 2

            # 3. Sarah checks `/api/v1/agent/me/summary` and `/api/v1/agent/me/feedback`
            summary_res = await client.get(
                "/api/v1/agent/me/summary",
                headers={"Authorization": f"Bearer {sarah_token}"},
            )
            assert summary_res.status_code == 200
            summary_body = summary_res.json()
            assert summary_body["kpis"]["unread_feedback_count"] >= 1
            assert summary_body["kpis"]["high_priority_unread_count"] >= 1

            inbox_res = await client.get(
                "/api/v1/agent/me/feedback",
                params={"readStatus": "UNREAD"},
                headers={"Authorization": f"Bearer {sarah_token}"},
            )
            assert inbox_res.status_code == 200
            inbox_ids = [item["id"] for item in inbox_res.json()["data"]]
            assert feedback_id in inbox_ids

            # 4. Other agent (Omar) cannot acknowledge Sarah's feedback -> 403 Forbidden
            omar_patch_res = await client.patch(
                f"/api/v1/feedback/{feedback_id}/status",
                headers={"Authorization": f"Bearer {omar_token}"},
                json={
                    "read_status": "ACKNOWLEDGED",
                    "completed_action_item_ids": ["act_1", "act_2"],
                    "agent_acknowledgement_note": "Trying to spoof acknowledgement.",
                },
            )
            assert omar_patch_res.status_code == 403

            # 5. Assigned agent (Sarah) acknowledges feedback & completes action items -> 200 OK
            sarah_patch_res = await client.patch(
                f"/api/v1/feedback/{feedback_id}/status",
                headers={"Authorization": f"Bearer {sarah_token}"},
                json={
                    "read_status": "ACKNOWLEDGED",
                    "completed_action_item_ids": ["act_1", "act_2"],
                    "agent_acknowledgement_note": (
                        "Understood! I reopened the ticket and verified the HMAC fix with the customer."
                    ),
                },
            )
            assert sarah_patch_res.status_code == 200
            patched = sarah_patch_res.json()
            assert patched["read_status"] == "ACKNOWLEDGED"
            assert patched["read_at"] is not None
            assert patched["acknowledged_at"] is not None
            assert (
                "reopened the ticket"
                in patched["agent_acknowledgement_note"]
            )
            assert all(
                item["completed"] is True for item in patched["action_items"]
            )
        finally:
            await _cleanup_tickets([ticket.id])
