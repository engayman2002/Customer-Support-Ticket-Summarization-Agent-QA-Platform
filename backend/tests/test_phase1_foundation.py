from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token, verify_password
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models import (
    AiQaReport,
    CoachingPriority,
    CrmType,
    FeedbackReadStatus,
    Integration,
    IssueCategory,
    ManagerFeedback,
    ProcessingStatus,
    ResolutionStatus,
    SentimentTrajectory,
    Ticket,
    TicketChannel,
    TicketPriority,
    User,
    UserRole,
)


@pytest.mark.asyncio
async def test_healthz_postgres_and_redis_healthy() -> None:
    """Verify `/healthz` returns 200 OK with both PostgreSQL and Redis healthy."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "healthy"
    assert body["redis"] == "healthy"
    assert body["services"]["postgres"] == "healthy"
    assert body["services"]["redis"] == "healthy"


@pytest.mark.asyncio
async def test_sqlalchemy_prisma_schema_and_enum_parity() -> None:
    """
    Verify SQLAlchemy 2.0 Async models query all Prisma-migrated and seeded records
    (`users`, `integrations`, `tickets`, `ai_qa_reports`, `manager_feedback`)
    with 1:1 column, relationship, and PostgreSQL Enum parity.
    """
    async with AsyncSessionLocal() as session:
        # 1. Verify Seeded Users & Hierarchy
        users_result = await session.execute(select(User).order_by(User.email))
        users = {u.email: u for u in users_result.scalars().all()}

        assert "admin@qa-platform.local" in users
        assert "manager@qa-platform.local" in users
        assert "sarah.agent@qa-platform.local" in users
        assert "omar.agent@qa-platform.local" in users

        admin = users["admin@qa-platform.local"]
        manager = users["manager@qa-platform.local"]
        sarah = users["sarah.agent@qa-platform.local"]
        omar = users["omar.agent@qa-platform.local"]

        assert admin.role == UserRole.ADMIN
        assert manager.role == UserRole.MANAGER
        assert sarah.role == UserRole.AGENT
        assert omar.role == UserRole.AGENT

        assert sarah.external_crm_agent_id == "zd_agent_101"
        assert omar.external_crm_agent_id == "zd_agent_102"
        assert sarah.manager_id == manager.id
        assert omar.manager_id == manager.id
        assert verify_password("Password123!", sarah.password_hash) is True

        # 2. Verify Seeded Integration
        integration_result = await session.execute(
            select(Integration).where(Integration.crm_type == CrmType.ZENDESK)
        )
        integration = integration_result.scalar_one()
        assert integration.is_active is True
        assert integration.subdomain_or_base_url == "https://acme-support.zendesk.com"
        assert isinstance(integration.config_metadata, dict)

        # 3. Verify Seeded Ticket + Eager-Loaded AI QA Report & Manager Feedback
        ticket_stmt = (
            select(Ticket)
            .where(Ticket.external_ticket_id == "ZD-99412")
            .options(
                selectinload(Ticket.ai_qa_report),
                selectinload(Ticket.manager_feedbacks),
                selectinload(Ticket.assigned_agent),
            )
        )
        ticket_result = await session.execute(ticket_stmt)
        ticket = ticket_result.scalar_one()

        assert ticket.assigned_agent_id == sarah.id
        assert ticket.assigned_agent.email == "sarah.agent@qa-platform.local"
        assert ticket.channel == TicketChannel.EMAIL
        assert ticket.priority == TicketPriority.HIGH
        assert ticket.processing_status == ProcessingStatus.EVALUATED
        assert isinstance(ticket.raw_transcript, list)
        assert len(ticket.raw_transcript) == 3

        # 4. Verify Seeded AI QA Report Enums & Metrics
        report: AiQaReport | None = ticket.ai_qa_report
        assert report is not None
        assert report.ticket_id == ticket.id
        assert report.issue_category == IssueCategory.TECHNICAL_BUG
        assert report.resolution_status == ResolutionStatus.PREMATURELY_CLOSED
        assert report.is_resolved_properly is False
        assert report.premature_closure_detected is True
        assert report.agent_score == 42
        assert report.empathy_rating == 6
        assert report.clarity_and_accuracy_rating == 5
        assert report.ownership_and_efficiency_rating == 3
        assert report.customer_sentiment_trajectory == SentimentTrajectory.DEGRADED
        assert report.model_used == "llama-3.3-70b-versatile"
        assert len(report.flagged_evidence_quotes) == 2
        assert len(report.actionable_coaching_plan) == 1

        # 5. Verify Seeded Manager Feedback
        assert len(ticket.manager_feedbacks) == 1
        feedback: ManagerFeedback = ticket.manager_feedbacks[0]
        assert feedback.manager_id == manager.id
        assert feedback.agent_id == sarah.id
        assert feedback.manager_override_score == 40
        assert feedback.coaching_priority == CoachingPriority.HIGH
        assert feedback.read_status == FeedbackReadStatus.UNREAD
        assert len(feedback.action_items) == 2

        # 6. Verify Agent RBAC Data Isolation Query (Sarah vs Omar)
        sarah_tickets = (
            await session.execute(
                select(Ticket).where(Ticket.assigned_agent_id == sarah.id)
            )
        ).scalars().all()
        omar_tickets = (
            await session.execute(
                select(Ticket).where(Ticket.assigned_agent_id == omar.id)
            )
        ).scalars().all()
        assert len(sarah_tickets) == 1
        assert len(omar_tickets) == 0


@pytest.mark.asyncio
async def test_unauthenticated_and_invalid_token_rejected_with_401() -> None:
    """Verify missing, tampered, or wrong-secret JWT tokens return 401 Unauthorized."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Missing Authorization header
        res_no_header = await client.get("/api/v1/auth/me")
        assert res_no_header.status_code == 401

        res_rbac_no_header = await client.get("/api/v1/manager/rbac-check")
        assert res_rbac_no_header.status_code == 401

        # Token signed with wrong secret
        wrong_secret_token = create_access_token(
            sub="11111111-1111-4111-8111-111111111102",
            email="manager@qa-platform.local",
            role=UserRole.MANAGER,
            secret_key="wrong-secret-key-that-must-fail-verification",
        )
        res_wrong_secret = await client.get(
            "/api/v1/manager/rbac-check",
            headers={"Authorization": f"Bearer {wrong_secret_token}"},
        )
        assert res_wrong_secret.status_code == 401

        # Expired token
        expired_token = create_access_token(
            sub="11111111-1111-4111-8111-111111111102",
            email="manager@qa-platform.local",
            role=UserRole.MANAGER,
            expires_delta=timedelta(minutes=-10),
        )
        res_expired = await client.get(
            "/api/v1/manager/rbac-check",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert res_expired.status_code == 401


@pytest.mark.asyncio
async def test_agent_jwt_receives_403_on_manager_rbac_route() -> None:
    """
    Verify an AGENT HS256 JWT token succeeds on `/api/v1/auth/me` (200 OK)
    but is strictly blocked from `/api/v1/manager/rbac-check` with 403 Forbidden.
    """
    agent_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111103",
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT,
        external_crm_agent_id="zd_agent_101",
        manager_id="11111111-1111-4111-8111-111111111102",
    )
    headers = {"Authorization": f"Bearer {agent_token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        me_res = await client.get("/api/v1/auth/me", headers=headers)
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["email"] == "sarah.agent@qa-platform.local"
        assert me_data["role"] == "AGENT"
        assert me_data["external_crm_agent_id"] == "zd_agent_101"

        rbac_res = await client.get("/api/v1/manager/rbac-check", headers=headers)
        assert rbac_res.status_code == 403
        assert "AGENT" in rbac_res.json()["detail"]


@pytest.mark.asyncio
async def test_manager_and_admin_jwt_receive_200_on_manager_rbac_route() -> None:
    """
    Verify both MANAGER and ADMIN HS256 JWT tokens signed with `AUTH_SECRET`
    are authorized (`200 OK`) on `/api/v1/manager/rbac-check`.
    """
    manager_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111102",
        email="manager@qa-platform.local",
        role=UserRole.MANAGER,
    )
    admin_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111101",
        email="admin@qa-platform.local",
        role=UserRole.ADMIN,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        manager_res = await client.get(
            "/api/v1/manager/rbac-check",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert manager_res.status_code == 200
        manager_body = manager_res.json()
        assert manager_body["status"] == "authorized"
        assert manager_body["user"]["role"] == "MANAGER"

        admin_res = await client.get(
            "/api/v1/manager/rbac-check",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_res.status_code == 200
        admin_body = admin_res.json()
        assert admin_body["status"] == "authorized"
        assert admin_body["user"]["role"] == "ADMIN"

