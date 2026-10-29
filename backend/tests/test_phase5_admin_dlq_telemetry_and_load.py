from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.v1.webhooks import flush_pending_ingestion_tasks
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.ai_qa_report import AiQaReport
from app.models.enums import ProcessingStatus, TicketChannel, TicketPriority, UserRole
from app.models.ticket import Ticket
from app.services.evaluation_service import mark_ticket_failed_and_route_to_dlq
from app.services.idempotency import get_redis_client


ADMIN_ID = "11111111-1111-4111-8111-111111111101"
AGENT_SARAH_ID = "11111111-1111-4111-8111-111111111103"
SEEDED_ZENDESK_INTEGRATION_ID = "22222222-2222-4222-8222-222222222201"
SEEDED_ZENDESK_SECRET = "dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d"


def _make_admin_headers() -> Dict[str, str]:
    token = create_access_token(
        sub=ADMIN_ID,
        email="admin@qa-platform.local",
        role=UserRole.ADMIN.value,
        external_crm_agent_id=None,
        manager_id=None,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_agent_headers() -> Dict[str, str]:
    token = create_access_token(
        sub=AGENT_SARAH_ID,
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT.value,
        external_crm_agent_id="zd_agent_101",
        manager_id="11111111-1111-4111-8111-111111111102",
    )
    return {"Authorization": f"Bearer {token}"}


def _sign_zendesk_payload(raw_body: bytes, timestamp_str: str, secret: str) -> str:
    signing_payload = timestamp_str.encode("utf-8") + raw_body
    digest = hmac.new(
        secret.encode("utf-8"),
        signing_payload,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


@pytest.mark.asyncio
async def test_phase5_admin_telemetry_and_rbac_enforcement() -> None:
    """
    Phase 5 Verification — Admin Observability Telemetry & RBAC Enforcement:
    1. Verifies `GET /api/v1/admin/telemetry` returns valid `p50_latency_ms`,
       `p95_latency_ms`, `p99_latency_ms`, token totals, fallback rate %, queue status,
       and integration health.
    2. Verifies `403 Forbidden` when an `AGENT` attempts to access `/api/v1/admin/telemetry`
       or `/api/v1/admin/dlq`.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. AGENT must be denied with 403 Forbidden
        agent_resp = await client.get(
            "/api/v1/admin/telemetry",
            headers=_make_agent_headers(),
        )
        assert agent_resp.status_code == 403

        agent_dlq_resp = await client.get(
            "/api/v1/admin/dlq",
            headers=_make_agent_headers(),
        )
        assert agent_dlq_resp.status_code == 403

        # 2. ADMIN receives complete telemetry payload
        admin_resp = await client.get(
            "/api/v1/admin/telemetry",
            headers=_make_admin_headers(),
        )
        assert admin_resp.status_code == 200
        payload = admin_resp.json()

        assert "queue_status" in payload
        assert payload["queue_status"]["counts_by_status"]["EVALUATED"] >= 1
        assert payload["queue_status"]["total_tickets"] >= 1
        assert "redis_dlq_length" in payload["queue_status"]

        latency = payload["latency_metrics"]
        assert latency["sample_size"] >= 1
        assert latency["p50_latency_ms"] > 0
        assert latency["p95_latency_ms"] >= latency["p50_latency_ms"]
        assert latency["p99_latency_ms"] >= latency["p95_latency_ms"]

        token_telemetry = payload["token_and_model_telemetry"]
        assert token_telemetry["total_prompt_tokens"] > 0
        assert token_telemetry["total_completion_tokens"] > 0
        assert token_telemetry["total_tokens"] == (
            token_telemetry["total_prompt_tokens"]
            + token_telemetry["total_completion_tokens"]
        )
        assert 0.0 <= token_telemetry["fallback_rate_pct"] <= 100.0

        assert payload["integration_health"]["total_integrations"] >= 1
        assert payload["integration_health"]["active_integrations"] >= 1


@pytest.mark.asyncio
async def test_phase5_dlq_inspection_and_one_click_replay() -> None:
    """
    Phase 5 Verification — DLQ Inspection & One-Click Replay (`Section 1.3 & 7`):
    1. Creates a temporary ticket and forces it into `FAILED_RETRYABLE` status
       while routing a failure envelope to Redis `ai_evaluation_dlq` via
       `mark_ticket_failed_and_route_to_dlq`.
    2. Verifies the ticket appears in `GET /api/v1/admin/dlq`.
    3. Invokes `POST /api/v1/admin/dlq/{ticket_id}/replay` as ADMIN.
    4. Asserts the ticket transitions to `EVALUATED`, persists an `AiQaReport`,
       and cleans up its DLQ envelope in Redis.
    """
    temp_ticket_id = uuid.uuid4()
    external_id = f"ZD-P5-DLQ-{temp_ticket_id.hex[:8]}"

    try:
        async with AsyncSessionLocal() as db:
            ticket = Ticket(
                id=temp_ticket_id,
                external_ticket_id=external_id,
                integration_id=uuid.UUID(SEEDED_ZENDESK_INTEGRATION_ID),
                assigned_agent_id=uuid.UUID(AGENT_SARAH_ID),
                customer_identifier="cust_hash_phase5_dlq_test",
                subject="Unable to export monthly billing CSV report",
                channel=TicketChannel.EMAIL,
                priority=TicketPriority.HIGH,
                raw_transcript=[
                    {
                        "message_id": "msg_dlq_1",
                        "sender_type": "CUSTOMER",
                        "author_name": "Customer",
                        "text": "Hello, when I click Export CSV on the billing tab, I get a 504 gateway timeout.",
                        "timestamp": "2026-10-29T10:00:00Z",
                    },
                    {
                        "message_id": "msg_dlq_2",
                        "sender_type": "AGENT",
                        "author_name": "Sarah Jenkins",
                        "text": "I understand how frustrating that timeout is. I have regenerated your billing index cache and verified the CSV export now downloads immediately.",
                        "timestamp": "2026-10-29T10:04:00Z",
                    },
                    {
                        "message_id": "msg_dlq_3",
                        "sender_type": "CUSTOMER",
                        "author_name": "Customer",
                        "text": "Thank you! The CSV downloaded right away.",
                        "timestamp": "2026-10-29T10:06:00Z",
                    },
                ],
                ticket_metadata={},
                ticket_created_at=datetime(2026, 10, 29, 10, 0, 0),
                ticket_closed_at=datetime(2026, 10, 29, 10, 7, 0),
                processing_status=ProcessingStatus.PROCESSING,
            )
            db.add(ticket)
            await db.commit()

            # Force ticket into FAILED_RETRYABLE and push envelope to Redis DLQ
            dlq_envelope = await mark_ticket_failed_and_route_to_dlq(
                ticket_id=temp_ticket_id,
                error_reason="Simulated Groq HTTP 503 Service Unavailable after 3 retries",
                db=db,
            )
            assert dlq_envelope["status"] == ProcessingStatus.FAILED_RETRYABLE.value

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Verify ticket appears in GET /api/v1/admin/dlq
            dlq_list_resp = await client.get(
                "/api/v1/admin/dlq",
                headers=_make_admin_headers(),
            )
            assert dlq_list_resp.status_code == 200
            dlq_data = dlq_list_resp.json()
            failed_ids = [t["ticket_id"] for t in dlq_data["failed_tickets"]]
            assert str(temp_ticket_id) in failed_ids

            # Trigger 1-Click Replay via POST /api/v1/admin/dlq/{ticket_id}/replay
            replay_resp = await client.post(
                f"/api/v1/admin/dlq/{temp_ticket_id}/replay",
                headers=_make_admin_headers(),
            )
            assert replay_resp.status_code == 200
            replay_body = replay_resp.json()
            assert replay_body["status"] == "REPLAYED_AND_EVALUATED"
            assert replay_body["processing_status"] == ProcessingStatus.EVALUATED.value
            assert replay_body["agent_score"] > 0

            # Verify ticket is no longer in FAILED_RETRYABLE list and has an AiQaReport
            dlq_after_resp = await client.get(
                "/api/v1/admin/dlq",
                headers=_make_admin_headers(),
            )
            assert dlq_after_resp.status_code == 200
            failed_ids_after = [
                t["ticket_id"] for t in dlq_after_resp.json()["failed_tickets"]
            ]
            assert str(temp_ticket_id) not in failed_ids_after

        async with AsyncSessionLocal() as db:
            report_stmt = select(AiQaReport).where(AiQaReport.ticket_id == temp_ticket_id)
            report = (await db.execute(report_stmt)).scalar_one_or_none()
            assert report is not None
            assert 0 <= report.agent_score <= 100
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AiQaReport).where(AiQaReport.ticket_id == temp_ticket_id))
            await db.execute(delete(Ticket).where(Ticket.id == temp_ticket_id))
            await db.commit()


@pytest.mark.asyncio
async def test_phase5_high_concurrency_100_webhook_load_and_sla() -> None:
    """
    Phase 5 Verification — High-Concurrency 100-Webhook Load & SLA Test (`Section 1.3 & 7`):
    Fires 100 concurrent signed Zendesk webhook requests via `asyncio.gather` against
    `POST /api/v1/webhooks/zendesk/{integration_id}` and asserts:
    1. 100% `202 Accepted` responses (`0` `5xx` errors).
    2. `p95` response latency `< 75ms` in the test environment.
    """
    batch_tag = uuid.uuid4().hex[:8]
    external_ticket_ids: List[str] = [
        f"ZD-LOAD100-{batch_tag}-{idx:03d}" for idx in range(100)
    ]
    closed_at_iso = "2026-10-29T18:30:00Z"
    timestamp_str = str(int(time.time()))

    prepared_requests: List[tuple[bytes, Dict[str, str]]] = []
    for ext_id in external_ticket_ids:
        payload = {
            "ticket": {
                "id": ext_id,
                "status": "closed",
                "subject": f"High concurrency load verification ticket {ext_id}",
                "priority": "normal",
                "assignee_id": "zd_agent_101",
                "requester_id": "cust_load_test",
                "created_at": "2026-10-29T18:00:00Z",
                "updated_at": closed_at_iso,
                "comments": [
                    {
                        "id": f"c1_{ext_id}",
                        "author_id": "cust_load_test",
                        "role": "end-user",
                        "body": "Need help resetting SSO login session.",
                        "created_at": "2026-10-29T18:01:00Z",
                    },
                    {
                        "id": f"c2_{ext_id}",
                        "author_id": "zd_agent_101",
                        "role": "agent",
                        "body": "I have cleared your SSO token cache and confirmed login is working.",
                        "created_at": "2026-10-29T18:10:00Z",
                    },
                ],
            }
        }
        raw_bytes = json.dumps(payload).encode("utf-8")
        signature = _sign_zendesk_payload(raw_bytes, timestamp_str, SEEDED_ZENDESK_SECRET)
        headers = {
            "Content-Type": "application/json",
            "X-Zendesk-Webhook-Signature": signature,
            "X-Zendesk-Webhook-Signature-Timestamp": timestamp_str,
        }
        prepared_requests.append((raw_bytes, headers))

    transport = ASGITransport(app=app)
    latencies_ms: List[float] = []
    status_codes: List[int] = []
    client_pool_semaphore = asyncio.Semaphore(25)

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Warm up Redis connection pool before firing the 100-request burst
            redis = get_redis_client()
            await redis.ping()

            async def _fire_single_webhook(raw_body: bytes, headers: Dict[str, str]) -> tuple[int, float]:
                async with client_pool_semaphore:
                    t0 = time.perf_counter()
                    resp = await client.post(
                        f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
                        content=raw_body,
                        headers=headers,
                    )
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    return resp.status_code, elapsed_ms

            results = await asyncio.gather(
                *[_fire_single_webhook(body, hdrs) for body, hdrs in prepared_requests]
            )

            for code, latency in results:
                status_codes.append(code)
                latencies_ms.append(latency)

            # Drain background ingestion tasks before cleanup
            await flush_pending_ingestion_tasks()

        # 1. Assert 100% 202 Accepted and 0% 5xx errors
        assert len(status_codes) == 100
        assert all(code == 202 for code in status_codes), f"Unexpected status codes: {set(status_codes)}"

        # 2. Compute p95 latency and assert < 75ms
        sorted_latencies = sorted(latencies_ms)
        p95_index = int(round(0.95 * (len(sorted_latencies) - 1)))
        p95_latency_ms = sorted_latencies[p95_index]
        assert p95_latency_ms < 75.0, f"p95 webhook latency {p95_latency_ms:.2f}ms exceeded 75ms SLA"
    finally:
        await flush_pending_ingestion_tasks()
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Ticket).where(Ticket.external_ticket_id.in_(external_ticket_ids))
            )
            await db.commit()

        redis = get_redis_client()
        dedup_keys = [
            f"webhook:dedup:ZENDESK:{ext_id}:{closed_at_iso}"
            for ext_id in external_ticket_ids
        ]
        if dedup_keys:
            await redis.delete(*dedup_keys)
