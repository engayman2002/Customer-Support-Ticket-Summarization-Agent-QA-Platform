from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.ai.evaluator import GroqTicketEvaluator
from app.ai.rate_limiter import reset_groq_rate_limit
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models import (
    AiQaReport,
    IssueCategory,
    ProcessingStatus,
    ResolutionStatus,
    SentimentTrajectory,
    Ticket,
    TicketChannel,
    TicketPriority,
    UserRole,
)
from app.schemas.qa_evaluation import (
    CoachingPlanItem,
    EvidenceIssueType,
    EvidenceSpeaker,
    FlaggedEvidenceQuote,
    TicketQAEvaluation,
)
from app.services.evaluation_service import (
    REDIS_AI_EVALUATION_DLQ_KEY,
    REDIS_QA_REPORT_READY_HISTORY_KEY,
    evaluate_and_persist_ticket,
)
from app.services.idempotency import get_redis_client
from app.worker.tasks import evaluate_ticket_ai_qa_async

SEEDED_ZENDESK_INTEGRATION_ID = uuid.UUID(
    "22222222-2222-4222-8222-222222222201"
)
SEEDED_SARAH_AGENT_ID = uuid.UUID("11111111-1111-4111-8111-111111111103")


async def _create_test_ticket(
    external_id_prefix: str,
    subject: str,
    transcript: List[Dict[str, Any]],
) -> Ticket:
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    ticket = Ticket(
        id=uuid.uuid4(),
        integration_id=SEEDED_ZENDESK_INTEGRATION_ID,
        external_ticket_id=f"{external_id_prefix}-{uuid.uuid4().hex[:8]}",
        assigned_agent_id=SEEDED_SARAH_AGENT_ID,
        customer_identifier="cust_hash_phase3b_test",
        subject=subject,
        channel=TicketChannel.EMAIL,
        priority=TicketPriority.HIGH,
        processing_status=ProcessingStatus.QUEUED,
        raw_transcript=transcript,
        ticket_metadata={"source": "phase3b_test"},
        first_response_time_seconds=120,
        total_resolution_time_seconds=900,
        ticket_created_at=now_naive,
        ticket_closed_at=now_naive,
    )
    async with AsyncSessionLocal() as db:
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)
    return ticket


async def _cleanup_test_tickets(ticket_ids: List[uuid.UUID]) -> None:
    if not ticket_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Ticket).where(Ticket.id.in_(ticket_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_chatgroq_structured_output_persistence_and_redis_notification() -> None:
    """
    Step 4.1: Verify end-to-end evaluation of a queued ticket persists an `AiQaReport`,
    transitions `Ticket.processing_status` to `EVALUATED`, and publishes to `qa_report_ready`.
    """
    ticket = await _create_test_ticket(
        external_id_prefix="ZD-P3B-EVAL",
        subject="Duplicate invoice charge on Pro plan renewal",
        transcript=[
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T10:00:00Z",
                "content": "Hi, my card was charged twice for invoice INV-501.",
            },
            {
                "sender_role": "AGENT",
                "timestamp": "2026-10-29T10:04:00Z",
                "content": (
                    "I sincerely apologize for the duplicate charge! I verified our Stripe ledger, "
                    "refunded the duplicate capture (ref_8821), and confirmed your Pro subscription is active."
                ),
            },
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T10:10:00Z",
                "content": "Thank you so much, I see the refund confirmation email now!",
            },
        ],
    )

    try:
        result = await evaluate_and_persist_ticket(
            ticket_id=ticket.id,
            bypass_rate_limit=True,
        )
        assert result["status"] == "EVALUATED"
        assert result["processing_status"] == ProcessingStatus.EVALUATED.value
        assert result["is_resolved_properly"] is True
        assert result["premature_closure_detected"] is False
        assert result["agent_score"] >= 80

        async with AsyncSessionLocal() as db:
            db_ticket = (
                await db.execute(select(Ticket).where(Ticket.id == ticket.id))
            ).scalar_one()
            assert db_ticket.processing_status == ProcessingStatus.EVALUATED
            assert db_ticket.ticket_metadata.get("fallback_model_used") is False

            db_report = (
                await db.execute(
                    select(AiQaReport).where(AiQaReport.ticket_id == ticket.id)
                )
            ).scalar_one()
            assert db_report.agent_score == result["agent_score"]
            assert db_report.resolution_status == ResolutionStatus.RESOLVED
            assert db_report.is_resolved_properly is True
            assert len(db_report.actionable_coaching_plan) >= 1

        redis_client = get_redis_client()
        recent_events = await redis_client.lrange(
            REDIS_QA_REPORT_READY_HISTORY_KEY, 0, 10
        )
        parsed_events = [json.loads(ev) for ev in recent_events]
        assert any(ev.get("ticket_id") == str(ticket.id) for ev in parsed_events)
    finally:
        await _cleanup_test_tickets([ticket.id])


@pytest.mark.asyncio
async def test_primary_model_429_503_failure_switches_to_fallback_model() -> None:
    """
    Step 4.2: Simulate `429 Rate Limit` / `503 Service Unavailable` on the primary
    `llama-3.3-70b-versatile` runnable and verify automatic fallback to `llama-3.1-8b-instant`
    with `fallback_model_used == True` and `Ticket.processing_status == ProcessingStatus.EVALUATED`.
    """
    ticket = await _create_test_ticket(
        external_id_prefix="ZD-P3B-FALLBACK",
        subject="Webhook signature verification guide",
        transcript=[
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T11:00:00Z",
                "content": "How do I verify the X-Webhook-Signature header in Python?",
            },
            {
                "sender_role": "AGENT",
                "timestamp": "2026-10-29T11:05:00Z",
                "content": (
                    "You can compute hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest() "
                    "and compare it with hmac.compare_digest. Let me know if that works!"
                ),
            },
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T11:12:00Z",
                "content": "Worked on the first try, thank you!",
            },
        ],
    )

    primary_attempts = 0
    fallback_attempts = 0

    async def failing_primary_runnable(_messages: Any) -> Any:
        nonlocal primary_attempts
        primary_attempts += 1
        raise RuntimeError(
            "Groq API HTTP 503 Service Unavailable / 429 Rate Limit on llama-3.3-70b-versatile"
        )

    async def succeeding_fallback_runnable(_messages: Any) -> Dict[str, Any]:
        nonlocal fallback_attempts
        fallback_attempts += 1
        return {
            "parsed": TicketQAEvaluation(
                summary=(
                    "Customer asked how to verify webhook HMAC signatures in Python. "
                    "Agent provided a working hmac.compare_digest code example and customer confirmed success."
                ),
                core_issue="HMAC-SHA256 webhook signature verification in Python.",
                issue_category=IssueCategory.HOW_TO,
                resolution_status=ResolutionStatus.RESOLVED,
                is_resolved_properly=True,
                premature_closure_detected=False,
                premature_closure_reason=None,
                agent_score=93,
                empathy_rating=9,
                clarity_and_accuracy_rating=10,
                ownership_and_efficiency_rating=9,
                customer_sentiment_trajectory=SentimentTrajectory.IMPROVED,
                strengths=["Provided exact hmac.compare_digest snippet."],
                areas_for_improvement=[],
                flagged_evidence_quotes=[],
                actionable_coaching_plan=[
                    CoachingPlanItem(
                        focus_area="Documentation Linking",
                        specific_action="Include a link to the official SDK webhook helper.",
                        suggested_phrasing_example="You can also use our Python SDK helper verify_webhook() shown in docs/webhooks.",
                    )
                ],
            ),
            "raw": None,
        }

    evaluator = GroqTicketEvaluator(
        primary_runnable=failing_primary_runnable,
        fallback_runnable=succeeding_fallback_runnable,
        max_retries=2,
        base_backoff_seconds=0.01,
    )

    try:
        result = await evaluate_and_persist_ticket(
            ticket_id=ticket.id,
            evaluator=evaluator,
            bypass_rate_limit=True,
        )
        assert primary_attempts == 2
        assert fallback_attempts == 1
        assert result["status"] == "EVALUATED"
        assert result["fallback_model_used"] is True
        assert "llama-3.1-8b-instant (fallback)" == result["model_used"]

        async with AsyncSessionLocal() as db:
            db_ticket = (
                await db.execute(select(Ticket).where(Ticket.id == ticket.id))
            ).scalar_one()
            assert db_ticket.processing_status == ProcessingStatus.EVALUATED
            assert db_ticket.ticket_metadata["fallback_model_used"] is True
    finally:
        await _cleanup_test_tickets([ticket.id])


@pytest.mark.asyncio
async def test_exhausted_retries_routes_ticket_to_dlq_failed_retryable() -> None:
    """
    Step 4.3: Simulate persistent failures across both primary and fallback models
    and verify the ticket transitions to `ProcessingStatus.FAILED_RETRYABLE` and
    triggers the Dead-Letter Queue (`ai_evaluation_dlq`).
    """
    ticket = await _create_test_ticket(
        external_id_prefix="ZD-P3B-DLQ",
        subject="Database connection timeout investigation",
        transcript=[
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T12:00:00Z",
                "content": "Our production cluster is throwing connection pool errors.",
            }
        ],
    )

    async def always_failing_runnable(_messages: Any) -> Any:
        raise RuntimeError("Upstream Groq cluster unreachable after all retries")

    evaluator = GroqTicketEvaluator(
        primary_runnable=always_failing_runnable,
        fallback_runnable=always_failing_runnable,
        max_retries=2,
        base_backoff_seconds=0.01,
    )

    redis_client = get_redis_client()
    dlq_len_before = await redis_client.llen(REDIS_AI_EVALUATION_DLQ_KEY)

    try:
        dlq_result = await evaluate_ticket_ai_qa_async(
            ticket_id=str(ticket.id),
            evaluator=evaluator,
            bypass_rate_limit=True,
        )
        assert dlq_result["status"] == ProcessingStatus.FAILED_RETRYABLE.value
        assert "Upstream Groq cluster unreachable" in dlq_result["error_reason"]

        dlq_len_after = await redis_client.llen(REDIS_AI_EVALUATION_DLQ_KEY)
        assert dlq_len_after > dlq_len_before

        async with AsyncSessionLocal() as db:
            db_ticket = (
                await db.execute(select(Ticket).where(Ticket.id == ticket.id))
            ).scalar_one()
            assert (
                db_ticket.processing_status == ProcessingStatus.FAILED_RETRYABLE
            )
            assert (
                "Upstream Groq cluster unreachable"
                in db_ticket.ticket_metadata.get("last_dlq_error", "")
            )
    finally:
        await _cleanup_test_tickets([ticket.id])


@pytest.mark.asyncio
async def test_20_ticket_gold_standard_synthetic_qa_evaluation_suite() -> None:
    """
    Step 4.4: 20-Ticket Gold-Standard Synthetic Test Suite:
    - 10 Properly Resolved Tickets -> `is_resolved_properly == True`, `premature_closure_detected == False`, `agent_score >= 75`.
    - 5 Prematurely Closed Tickets -> `premature_closure_detected == True`, `resolution_status == PREMATURELY_CLOSED`,
      `is_resolved_properly == False`, `agent_score <= 45`.
    - 5 Rude/Unhelpful Agent Tickets -> `is_resolved_properly == False`, `flagged_evidence_quotes` non-empty
      (`POOR_TONE` or `UNHELPFUL_RESPONSE`), and `agent_score <= 35`.
    """
    evaluator = GroqTicketEvaluator(api_key="")

    # 1. 10 Properly Resolved Tickets
    resolved_cases: List[Dict[str, Any]] = [
        {
            "subject": f"Resolved Case #{i + 1}: {topic}",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": cust_msg,
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:10:00Z",
                    "content": agent_msg,
                },
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:20:00Z",
                    "content": "That completely solved my issue, thank you for the fast help!",
                },
            ],
        }
        for i, (topic, cust_msg, agent_msg) in enumerate(
            [
                (
                    "Duplicate Billing Charge",
                    "I was charged twice on invoice #9001.",
                    "I verified the duplicate capture and issued full refund ref_101 to your card.",
                ),
                (
                    "SSO SAML Certificate Rotation",
                    "Our Okta SAML login failed after rotating our X509 cert.",
                    "I updated your IdP metadata fingerprint in your tenant settings and verified the SAML assertion.",
                ),
                (
                    "API Rate Limit Quota Upgrade",
                    "Can you increase our webhook throughput tier?",
                    "I upgraded your organization quota to 500 RPS and confirmed the new limit is active.",
                ),
                (
                    "CSV Export Encoding Fix",
                    "Exported CSV files show garbled UTF-8 characters in Excel.",
                    "I enabled UTF-8 BOM encoding on your workspace export profile so Excel renders symbols properly.",
                ),
                (
                    "Two-Factor Recovery Reset",
                    "Our team lead lost their authenticator phone and is locked out.",
                    "After verifying domain ownership, I reset MFA for the account and sent a recovery link.",
                ),
                (
                    "Custom Domain TLS Provisioning",
                    "Our custom portal domain ssl cert is stuck in pending.",
                    "I flushed the CAA DNS cache and completed Let's Encrypt certificate provisioning for your domain.",
                ),
                (
                    "Subscription Seat Proration",
                    "We removed 5 inactive seats and want to confirm next month's invoice.",
                    "I applied the 5-seat reduction and confirmed a prorated credit of 250 USD on your next billing cycle.",
                ),
                (
                    "Webhook Retry Policy Configuration",
                    "How do we configure exponential backoff for custom webhooks?",
                    "I enabled automatic 5-attempt exponential backoff on your endpoint and shared the delivery logs.",
                ),
                (
                    "Role Permission Assignment",
                    "Our QA manager cannot view team scorecards.",
                    "I updated their role from AGENT to MANAGER and confirmed team analytics access is active.",
                ),
                (
                    "Audit Log Retention Export",
                    "We need a 90-day security audit archive for SOC2 compliance.",
                    "I generated the signed 90-day JSONL audit archive and enabled it in your security downloads tab.",
                ),
            ]
        )
    ]

    # 2. 5 Premature Closure Tickets (covering all 4 Section 3.3 Premature Closure rules)
    premature_cases: List[Dict[str, Any]] = [
        # Case 1: Last-Word Unresolved Question
        {
            "subject": "Premature #1: Last-word unresolved customer question",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "My API key is returning 403 Forbidden on the /tickets endpoint.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:10:00Z",
                    "content": "Try regenerating your token in the dashboard.",
                },
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:15:00Z",
                    "content": "I regenerated the token and it is still not working! Why am I still getting 403?",
                },
            ],
        },
        # Case 2: Drive-By Link Drop
        {
            "subject": "Premature #2: Drive-by generic link drop without confirmation",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "Our production SSO integration is completely down for 200 users.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:05:00Z",
                    "content": "Check our FAQ here: https://help.example.com/articles/sso-faq. Closing this ticket now.",
                },
            ],
        },
        # Case 3: Ghost Closure < 24h after asking customer for diagnostic logs
        {
            "subject": "Premature #3: Ghost closure 20 minutes after asking for screenshot",
            "closed_at": "2026-10-29T14:30:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "The billing page crashes when I click Update Card.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:10:00Z",
                    "content": "Can you send a screenshot of your browser console and network tab?",
                },
            ],
        },
        # Case 4: Multi-Part Inquiry Neglect
        {
            "subject": "Premature #4: Multi-part inquiry where second question was ignored",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": (
                        "I have two questions: 1) Where do I download my October invoice? "
                        "2) How do I configure SAML JIT role mapping for our engineering group?"
                    ),
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:08:00Z",
                    "content": "Invoices are in Settings > Billing.",
                },
            ],
        },
        # Case 5: Customer explicitly reports fix did not work before closure
        {
            "subject": "Premature #5: Customer reported fix did not resolve the crash",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "The mobile app crashes on launch after v4.2 update.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:10:00Z",
                    "content": "Please clear the app cache and restart your phone.",
                },
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:18:00Z",
                    "content": "I cleared the cache and restarted, but that didn't fix it—still getting the same error!",
                },
            ],
        },
    ]

    # 3. 5 Rude / Hostile / Unhelpful Agent Tickets
    rude_cases: List[Dict[str, Any]] = [
        {
            "subject": "Rude #1: Agent blames customer and tells them to read the manual",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "I am confused about how the webhook timestamp header should be formatted.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:05:00Z",
                    "content": "If you had read the manual instead of wasting our time, you would know it is ISO-8601.",
                },
            ],
        },
        {
            "subject": "Rude #2: Agent tells customer to stop reopening the ticket",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "My export is still stuck at 0% after 3 hours.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:06:00Z",
                    "content": "Stop reopening this ticket and figure it out yourself. That is not my problem.",
                },
            ],
        },
        {
            "subject": "Rude #3: Hostile dismissive remark blaming user error",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "Our webhook secret rotation caused 401 errors.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:07:00Z",
                    "content": "This is your own fault and user error, obviously. Stop complaining to support.",
                },
            ],
        },
        {
            "subject": "Rude #4: Condescending refusal to help",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "Can you help me debug why our Freshdesk sync skipped 2 tickets?",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:09:00Z",
                    "content": "As I already told you, learn how to use the API and do it yourself.",
                },
            ],
        },
        {
            "subject": "Rude #5: Unhelpful brush-off and abrupt closure",
            "closed_at": "2026-10-29T15:00:00Z",
            "turns": [
                {
                    "sender_role": "CUSTOMER",
                    "timestamp": "2026-10-29T14:00:00Z",
                    "content": "We are seeing intermittent 502 Bad Gateway responses from your EU endpoint.",
                },
                {
                    "sender_role": "AGENT",
                    "timestamp": "2026-10-29T14:11:00Z",
                    "content": "Works on my machine, we don't care about your local network. Cannot help you with that, bye.",
                },
            ],
        },
    ]

    assert len(resolved_cases) == 10
    assert len(premature_cases) == 5
    assert len(rude_cases) == 5

    # Evaluate all 10 Properly Resolved Tickets
    for case in resolved_cases:
        res = await evaluator.evaluate_ticket(
            ticket_metadata={
                "subject": case["subject"],
                "closed_at": case["closed_at"],
            },
            raw_transcript=case["turns"],
        )
        ev = res.evaluation
        assert isinstance(ev, TicketQAEvaluation)
        assert ev.is_resolved_properly is True, f"Failed on {case['subject']}"
        assert ev.premature_closure_detected is False
        assert ev.resolution_status in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.ESCALATED_PROPERLY,
        }
        assert ev.agent_score >= 75

    # Evaluate all 5 Premature Closure Tickets
    for case in premature_cases:
        res = await evaluator.evaluate_ticket(
            ticket_metadata={
                "subject": case["subject"],
                "closed_at": case["closed_at"],
            },
            raw_transcript=case["turns"],
        )
        ev = res.evaluation
        assert isinstance(ev, TicketQAEvaluation)
        assert ev.premature_closure_detected is True, (
            f"Expected premature closure on {case['subject']}"
        )
        assert ev.resolution_status == ResolutionStatus.PREMATURELY_CLOSED
        assert ev.is_resolved_properly is False
        assert ev.agent_score <= 45
        assert ev.premature_closure_reason is not None

    # Evaluate all 5 Rude / Unhelpful Tickets
    for case in rude_cases:
        res = await evaluator.evaluate_ticket(
            ticket_metadata={
                "subject": case["subject"],
                "closed_at": case["closed_at"],
            },
            raw_transcript=case["turns"],
        )
        ev = res.evaluation
        assert isinstance(ev, TicketQAEvaluation)
        assert ev.is_resolved_properly is False, f"Failed on {case['subject']}"
        assert ev.agent_score <= 35
        assert len(ev.flagged_evidence_quotes) >= 1
        assert any(
            q.issue_type
            in {
                EvidenceIssueType.POOR_TONE,
                EvidenceIssueType.UNHELPFUL_RESPONSE,
            }
            for q in ev.flagged_evidence_quotes
        )


@pytest.mark.asyncio
async def test_100_ticket_burst_concurrency_and_rate_limiter_resilience() -> None:
    """
    Step 4.5: Burst-enqueue 100 tickets simultaneously under active RPM/TPM rate limiting
    (`rpm_limit=30, tpm_limit=15000`) and verify:
    - Zero dropped tasks and zero unhandled 429 crashes.
    - Exactly 30 tickets are allowed per RPM window while the remaining 70 are cleanly
      deferred (`status == "RATE_LIMITED"`, `retry_after_seconds > 0`).
    - Subsequent window drains evaluate all remaining deferred tickets until 100/100 complete.
    """
    burst_scope = f"burst_100_{uuid.uuid4().hex[:8]}"
    ticket_ids = [str(uuid.uuid4()) for _ in range(100)]

    evaluated_tickets: set[str] = set()
    deferred_retry_events: int = 0

    async def simulated_worker_attempt(t_id: str) -> Dict[str, Any]:
        from app.ai.rate_limiter import acquire_groq_rate_limit

        allowed, retry_after = await acquire_groq_rate_limit(
            estimated_tokens=400,
            rpm_limit=30,
            tpm_limit=15000,
            scope=burst_scope,
        )
        if not allowed:
            return {
                "ticket_id": t_id,
                "status": "RATE_LIMITED",
                "retry_after_seconds": retry_after,
            }
        return {
            "ticket_id": t_id,
            "status": "EVALUATED",
            "retry_after_seconds": 0.0,
        }

    try:
        pending_ids = list(ticket_ids)
        window_iterations = 0

        while pending_ids and window_iterations < 5:
            window_iterations += 1
            batch_results = await asyncio.gather(
                *(simulated_worker_attempt(tid) for tid in pending_ids)
            )
            next_pending: List[str] = []
            for item in batch_results:
                if item["status"] == "EVALUATED":
                    evaluated_tickets.add(item["ticket_id"])
                else:
                    assert item["status"] == "RATE_LIMITED"
                    assert item["retry_after_seconds"] > 0.0
                    deferred_retry_events += 1
                    next_pending.append(item["ticket_id"])

            if window_iterations == 1:
                # First burst of 100 against 30 RPM limit must evaluate 30 and defer 70
                assert len(evaluated_tickets) == 30
                assert len(next_pending) == 70

            pending_ids = next_pending
            if pending_ids:
                # Advance to next rate-limit window
                await reset_groq_rate_limit(scope=burst_scope)

        # All 100 tickets accounted for and evaluated across 4 windows (30 + 30 + 30 + 10 = 100)
        assert len(evaluated_tickets) == 100
        assert deferred_retry_events == 70 + 40 + 10
    finally:
        await reset_groq_rate_limit(scope=burst_scope)


@pytest.mark.asyncio
async def test_re_evaluate_ticket_endpoint_rbac_and_execution() -> None:
    """
    Step 4.6: Verify `POST /api/v1/tickets/{id}/re-evaluate`:
    - `AGENT` receives `403 Forbidden`.
    - `MANAGER` and `ADMIN` receive `200 OK` with an updated `AiQaReport`.
    - Unknown ticket UUID returns `404 Not Found`.
    """
    agent_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111103",
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT,
    )
    manager_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111102",
        email="manager@qa-platform.local",
        role=UserRole.MANAGER,
    )

    ticket = await _create_test_ticket(
        external_id_prefix="ZD-P3B-REEVAL",
        subject=" Premature closure re-evaluation check",
        transcript=[
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T13:00:00Z",
                "content": "My dashboard export failed with error 504.",
            },
            {
                "sender_role": "AGENT",
                "timestamp": "2026-10-29T13:05:00Z",
                "content": "Please try again.",
            },
            {
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-29T13:08:00Z",
                "content": "I tried again and it is still failing with 504! Can you check the server logs?",
            },
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            # 1. AGENT -> 403 Forbidden
            forbidden_res = await client.post(
                f"/api/v1/tickets/{ticket.id}/re-evaluate",
                headers={"Authorization": f"Bearer {agent_token}"},
            )
            assert forbidden_res.status_code == 403

            # 2. Unknown Ticket UUID -> 404 Not Found
            unknown_res = await client.post(
                f"/api/v1/tickets/{uuid.uuid4()}/re-evaluate",
                headers={"Authorization": f"Bearer {manager_token}"},
            )
            assert unknown_res.status_code == 404

            # 3. MANAGER -> 200 OK & updated AiQaReport
            ok_res = await client.post(
                f"/api/v1/tickets/{ticket.id}/re-evaluate",
                headers={"Authorization": f"Bearer {manager_token}"},
            )
            assert ok_res.status_code == 200
            body = ok_res.json()
            assert body["status"] == "EVALUATED"
            assert body["ticket_id"] == str(ticket.id)
            assert body["processing_status"] == "EVALUATED"
            assert body["premature_closure_detected"] is True
            assert body["resolution_status"] == "PREMATURELY_CLOSED"
            assert body["agent_score"] <= 45
            assert body["triggered_by"] == "manager@qa-platform.local"
        finally:
            await _cleanup_test_tickets([ticket.id])

