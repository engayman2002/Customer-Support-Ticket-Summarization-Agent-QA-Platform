from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.api.v1.webhooks import flush_pending_ingestion_tasks
from app.core.crypto import AES_GCM_PREFIX, decrypt_secret
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models import (
    CrmType,
    Integration,
    ProcessingStatus,
    Ticket,
    UserRole,
)
from app.services.idempotency import (
    REDIS_INGESTION_QUEUE_KEY,
    get_redis_client,
)
from app.services.sanitizer import REDACTED_TOKEN
from app.worker.celery_app import (
    AI_EVALUATION_DLQ_NAME,
    AI_EVALUATION_QUEUE_NAME,
    INGESTION_QUEUE_NAME,
    celery_app,
)

SEEDED_ZENDESK_INTEGRATION_ID = "22222222-2222-4222-8222-222222222201"
SEEDED_ZENDESK_WEBHOOK_SECRET = (
    "dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d"
)


def _sign_zendesk_webhook(
    raw_body: bytes,
    timestamp_iso: str,
    secret: str = SEEDED_ZENDESK_WEBHOOK_SECRET,
) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        timestamp_iso.encode("utf-8") + raw_body,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def test_celery_queue_topology_and_beat_schedule() -> None:
    """
    Verify Celery defines `ingestion_queue`, `ai_evaluation_queue`, and `ai_evaluation_dlq`,
    routes tasks appropriately, and schedules the 15-minute Beat delta-sync reconciler.
    """
    configured_queues = {q.name for q in celery_app.conf.task_queues}
    assert INGESTION_QUEUE_NAME in configured_queues
    assert AI_EVALUATION_QUEUE_NAME in configured_queues
    assert AI_EVALUATION_DLQ_NAME in configured_queues

    routes = celery_app.conf.task_routes
    assert (
        routes["app.worker.tasks.process_webhook_ingestion_task"]["queue"]
        == INGESTION_QUEUE_NAME
    )
    assert (
        routes["app.worker.tasks.evaluate_ticket_ai_qa_task"]["queue"]
        == AI_EVALUATION_QUEUE_NAME
    )
    assert (
        routes["app.worker.tasks.handle_ai_evaluation_dlq_task"]["queue"]
        == AI_EVALUATION_DLQ_NAME
    )

    beat_entry = celery_app.conf.beat_schedule[
        "reconcile-closed-tickets-every-15-minutes"
    ]
    assert (
        beat_entry["task"] == "app.worker.tasks.reconcile_closed_tickets_task"
    )
    assert beat_entry["schedule"] == 900.0


@pytest.mark.asyncio
async def test_valid_zendesk_and_intercom_webhooks_sub_50ms_and_db_persistence() -> None:
    """
    Verify simulated Zendesk and Intercom "Ticket Closed" webhooks with valid HMAC
    signatures return `202 Accepted` in under 50ms and persist normalized `Ticket`
    records with `processing_status = QUEUED` and PII-redacted transcripts.
    """
    admin_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111101",
        email="admin@qa-platform.local",
        role=UserRole.ADMIN,
    )
    unique_suffix = uuid.uuid4().hex[:8]
    zd_ext_id = f"ZD-LIVE-{unique_suffix}"
    ic_ext_id = f"IC-LIVE-{unique_suffix}"
    intercom_secret = "ic_whsec_live_secret_2026"
    created_integration_id: str | None = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            # Create an active Intercom integration for the Intercom webhook test
            create_ic_res = await client.post(
                "/api/v1/integrations",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "name": f"Intercom Test {unique_suffix}",
                    "crm_type": "INTERCOM",
                    "subdomain_or_base_url": "https://api.intercom.io",
                    "api_key": "ic_api_key_secret_123",
                    "webhook_secret": intercom_secret,
                    "is_active": True,
                },
            )
            assert create_ic_res.status_code == 201
            created_integration_id = create_ic_res.json()["id"]

            # Warm up Redis connection on active event loop
            redis_client = get_redis_client()
            await redis_client.ping()

            # 1. Zendesk Closed Ticket Webhook
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            zd_payload = {
                "ticket": {
                    "id": zd_ext_id,
                    "status": "closed",
                    "assignee_id": "zd_agent_101",
                    "assignee_email": "sarah.agent@qa-platform.local",
                    "requester_email": "customer_pii@example.com",
                    "subject": "Card 4532-0151-1283-0366 declined on checkout",
                    "via": {"channel": "email"},
                    "priority": "high",
                    "created_at": "2026-10-29T10:00:00Z",
                    "updated_at": now_iso,
                    "comments": [
                        {
                            "id": "c_101",
                            "author_id": "cust_99",
                            "public": True,
                            "created_at": "2026-10-29T10:00:00Z",
                            "body": "<p>My credit card 4532-0151-1283-0366 failed.</p>",
                        },
                        {
                            "id": "c_102",
                            "author_id": "zd_agent_101",
                            "public": True,
                            "created_at": "2026-10-29T10:05:00Z",
                            "body": "<p>We cleared the fraud hold on your account.</p>",
                        },
                    ],
                }
            }
            zd_raw = json.dumps(zd_payload).encode("utf-8")
            zd_sig = _sign_zendesk_webhook(zd_raw, now_iso)

            t0 = time.perf_counter()
            zd_res = await client.post(
                f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
                content=zd_raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Zendesk-Webhook-Signature": zd_sig,
                    "X-Zendesk-Webhook-Signature-Timestamp": now_iso,
                },
            )
            zd_elapsed_ms = (time.perf_counter() - t0) * 1000.0

            assert zd_res.status_code == 202
            zd_body = zd_res.json()
            assert zd_body["status"] == "ACCEPTED"
            assert zd_body["idempotent_duplicate"] is False
            assert zd_body["job_id"].startswith("job_")
            assert zd_elapsed_ms < 50.0, (
                f"Expected webhook latency < 50ms, got {zd_elapsed_ms:.2f}ms"
            )

            # 2. Intercom Closed Conversation Webhook
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            ic_payload = {
                "topic": "conversation.admin.closed",
                "created_at": now_epoch,
                "conversation": {
                    "id": ic_ext_id,
                    "state": "closed",
                    "admin_assignee_id": "zd_agent_102",
                    "agent_email": "omar.agent@qa-platform.local",
                    "title": "Token rotation question",
                    "priority": "normal",
                    "created_at": now_epoch - 600,
                    "statistics": {
                        "last_close_at": now_epoch,
                        "time_to_admin_reply": 90,
                    },
                    "source": {
                        "id": "src_99",
                        "delivered_as": "messenger",
                        "body": "<div>My secret token sk_live_9876543210abcdef stopped working.</div>",
                        "author": {"id": "u_88", "name": "Alice"},
                    },
                },
            }
            ic_raw = json.dumps(ic_payload).encode("utf-8")
            ic_hex = hmac.new(
                intercom_secret.encode("utf-8"), ic_raw, hashlib.sha256
            ).hexdigest()

            t1 = time.perf_counter()
            ic_res = await client.post(
                f"/api/v1/webhooks/intercom/{created_integration_id}",
                content=ic_raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": f"sha256={ic_hex}",
                    "X-Intercom-Timestamp": str(now_epoch),
                },
            )
            ic_elapsed_ms = (time.perf_counter() - t1) * 1000.0

            assert ic_res.status_code == 202
            assert ic_res.json()["idempotent_duplicate"] is False
            assert ic_elapsed_ms < 50.0, (
                f"Expected Intercom webhook latency < 50ms, got {ic_elapsed_ms:.2f}ms"
            )

            # Wait for background ingestion tasks to finish persisting to PostgreSQL
            await flush_pending_ingestion_tasks()

            # 3. Verify PostgreSQL Persistence (`processing_status = QUEUED` & PII Redacted)
            async with AsyncSessionLocal() as db:
                zd_ticket = (
                    await db.execute(
                        select(Ticket).where(
                            Ticket.external_ticket_id == zd_ext_id
                        )
                    )
                ).scalar_one()
                assert zd_ticket.processing_status == ProcessingStatus.QUEUED
                assert REDACTED_TOKEN in zd_ticket.raw_transcript[0]["content"]
                assert (
                    "4532-0151-1283-0366"
                    not in zd_ticket.raw_transcript[0]["content"]
                )

                ic_ticket = (
                    await db.execute(
                        select(Ticket).where(
                            Ticket.external_ticket_id == ic_ext_id
                        )
                    )
                ).scalar_one()
                assert ic_ticket.processing_status == ProcessingStatus.QUEUED
                assert REDACTED_TOKEN in ic_ticket.raw_transcript[0]["content"]
                assert (
                    "sk_live_9876543210abcdef"
                    not in ic_ticket.raw_transcript[0]["content"]
                )
        finally:
            await flush_pending_ingestion_tasks()
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(Ticket).where(
                        Ticket.external_ticket_id.in_([zd_ext_id, ic_ext_id])
                    )
                )
                if created_integration_id:
                    await db.execute(
                        delete(Integration).where(
                            Integration.id == uuid.UUID(created_integration_id)
                        )
                    )
                await db.commit()


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_hmac_and_expired_timestamp_with_401() -> None:
    """
    Verify tampered webhook payloads or expired timestamps (> 300 seconds old)
    are rejected with `401 Unauthorized`.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=600)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw_body = json.dumps(
        {"ticket": {"id": "ZD-TAMPER-1", "status": "closed"}}
    ).encode("utf-8")
    tampered_body = json.dumps(
        {"ticket": {"id": "ZD-TAMPER-1", "status": "closed", "priority": "low"}}
    ).encode("utf-8")

    valid_sig_for_raw = _sign_zendesk_webhook(raw_body, now_iso)
    expired_sig = _sign_zendesk_webhook(raw_body, expired_iso)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Tampered body with valid signature for original body -> 401
        res_tampered = await client.post(
            f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                "X-Zendesk-Webhook-Signature": valid_sig_for_raw,
                "X-Zendesk-Webhook-Signature-Timestamp": now_iso,
            },
        )
        assert res_tampered.status_code == 401

        # 2. Expired timestamp (600s > 300s replay window) -> 401
        res_expired = await client.post(
            f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Zendesk-Webhook-Signature": expired_sig,
                "X-Zendesk-Webhook-Signature-Timestamp": expired_iso,
            },
        )
        assert res_expired.status_code == 401


@pytest.mark.asyncio
async def test_webhook_ignores_non_closed_ticket_events_with_200() -> None:
    """
    Verify webhook events where ticket status is `open` or `pending` return
    `200 OK` (`status = IGNORED_NOT_CLOSED`) and persist zero database rows.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    open_ticket_id = f"ZD-OPEN-{uuid.uuid4().hex[:8]}"
    raw_body = json.dumps(
        {
            "ticket": {
                "id": open_ticket_id,
                "status": "open",
                "subject": "Still investigating issue",
                "updated_at": now_iso,
            }
        }
    ).encode("utf-8")
    sig = _sign_zendesk_webhook(raw_body, now_iso)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Zendesk-Webhook-Signature": sig,
                "X-Zendesk-Webhook-Signature-Timestamp": now_iso,
            },
        )

    assert res.status_code == 200
    assert res.json()["status"] == "IGNORED_NOT_CLOSED"

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(Ticket)
                .where(Ticket.external_ticket_id == open_ticket_id)
            )
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_webhook_strict_idempotency_single_db_record_and_queue_job() -> None:
    """
    Verify sending the identical closed ticket webhook payload twice returns
    `idempotent_duplicate == False` on the 1st request and `True` on the 2nd,
    resulting in exactly ONE database record and ONE queued job.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dedup_ticket_id = f"ZD-DEDUP-{uuid.uuid4().hex[:8]}"
    payload = {
        "ticket": {
            "id": dedup_ticket_id,
            "status": "closed",
            "assignee_id": "zd_agent_101",
            "assignee_email": "sarah.agent@qa-platform.local",
            "subject": "Duplicate webhook delivery test",
            "created_at": "2026-10-29T11:00:00Z",
            "updated_at": now_iso,
            "comments": [
                {
                    "id": "c_dedup_1",
                    "public": True,
                    "created_at": "2026-10-29T11:00:00Z",
                    "body": "Issue resolved, thank you!",
                }
            ],
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = _sign_zendesk_webhook(raw_body, now_iso)
    headers = {
        "Content-Type": "application/json",
        "X-Zendesk-Webhook-Signature": sig,
        "X-Zendesk-Webhook-Signature-Timestamp": now_iso,
    }

    redis_client = get_redis_client()
    queue_len_before = await redis_client.llen(REDIS_INGESTION_QUEUE_KEY)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            # First delivery -> accepted and enqueued
            res_1 = await client.post(
                f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
                content=raw_body,
                headers=headers,
            )
            assert res_1.status_code == 202
            assert res_1.json()["idempotent_duplicate"] is False

            # Second identical delivery -> accepted as idempotent duplicate
            res_2 = await client.post(
                f"/api/v1/webhooks/zendesk/{SEEDED_ZENDESK_INTEGRATION_ID}",
                content=raw_body,
                headers=headers,
            )
            assert res_2.status_code == 202
            assert res_2.json()["idempotent_duplicate"] is True

            await flush_pending_ingestion_tasks()

            queue_len_after = await redis_client.llen(REDIS_INGESTION_QUEUE_KEY)
            assert queue_len_after - queue_len_before == 1

            async with AsyncSessionLocal() as db:
                ticket_count = (
                    await db.execute(
                        select(func.count())
                        .select_from(Ticket)
                        .where(Ticket.external_ticket_id == dedup_ticket_id)
                    )
                ).scalar_one()
                assert ticket_count == 1
        finally:
            await flush_pending_ingestion_tasks()
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(Ticket).where(
                        Ticket.external_ticket_id == dedup_ticket_id
                    )
                )
                await db.commit()


@pytest.mark.asyncio
async def test_admin_integration_creation_aes256gcm_and_manual_sync_reconciler() -> None:
    """
    Verify:
    1. AGENT cannot create integrations (`403 Forbidden`).
    2. ADMIN creates a new integration with credentials encrypted via AES-256-GCM (`enc_aes256gcm_v1:`).
    3. `POST /api/v1/integrations/{id}/sync` backfills missed closed tickets without duplicating
       already-ingested tickets and advances `last_successful_sync_at`.
    """
    agent_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111103",
        email="sarah.agent@qa-platform.local",
        role=UserRole.AGENT,
    )
    admin_token = create_access_token(
        sub="11111111-1111-4111-8111-111111111101",
        email="admin@qa-platform.local",
        role=UserRole.ADMIN,
    )

    unique_suffix = uuid.uuid4().hex[:8]
    sync_ticket_id = f"FD-SYNC-{unique_suffix}"
    created_integration_id: str | None = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            # 1. AGENT attempt -> 403 Forbidden
            forbidden_res = await client.post(
                "/api/v1/integrations",
                headers={"Authorization": f"Bearer {agent_token}"},
                json={
                    "name": "Unauthorized Integration",
                    "crm_type": "FRESHDESK",
                    "subdomain_or_base_url": "https://acme.freshdesk.com",
                    "api_key": "fd_key",
                    "webhook_secret": "fd_secret",
                },
            )
            assert forbidden_res.status_code == 403

            # 2. ADMIN creates Freshdesk Integration -> 201 Created
            raw_api_key = "fd_live_api_key_998877"
            raw_webhook_secret = "fd_live_webhook_secret_112233"
            create_res = await client.post(
                "/api/v1/integrations",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "name": f"Freshdesk Enterprise {unique_suffix}",
                    "crm_type": "FRESHDESK",
                    "subdomain_or_base_url": "https://acme.freshdesk.com",
                    "api_key": raw_api_key,
                    "webhook_secret": raw_webhook_secret,
                    "config_metadata": {"region": "us-east"},
                },
            )
            assert create_res.status_code == 201
            created_body = create_res.json()
            created_integration_id = created_body["id"]
            assert created_body["webhook_url"].endswith(
                f"/api/v1/webhooks/freshdesk/{created_integration_id}"
            )
            assert "encrypted_api_key" not in created_body

            # Verify AES-256-GCM encryption at rest in PostgreSQL
            async with AsyncSessionLocal() as db:
                db_integration = (
                    await db.execute(
                        select(Integration).where(
                            Integration.id == uuid.UUID(created_integration_id)
                        )
                    )
                ).scalar_one()
                assert db_integration.crm_type == CrmType.FRESHDESK
                assert db_integration.encrypted_api_key.startswith(
                    AES_GCM_PREFIX
                )
                assert db_integration.encrypted_webhook_secret.startswith(
                    AES_GCM_PREFIX
                )
                assert (
                    decrypt_secret(db_integration.encrypted_api_key)
                    == raw_api_key
                )
                assert (
                    decrypt_secret(db_integration.encrypted_webhook_secret)
                    == raw_webhook_secret
                )

            # 3. Trigger Manual Delta-Sync Backfill (`POST /api/v1/integrations/{id}/sync`)
            backfill_ticket_payload = {
                "ticket": {
                    "id": sync_ticket_id,
                    "status": 5,
                    "responder_id": "zd_agent_101",
                    "responder_email": "sarah.agent@qa-platform.local",
                    "subject": "Backfilled closed ticket from Freshdesk delta-sync",
                    "source": 1,
                    "priority": 2,
                    "created_at": "2026-10-29T09:00:00Z",
                    "stats": {"closed_at": "2026-10-29T09:45:00Z"},
                    "conversations": [
                        {
                            "id": "fdc_sync_1",
                            "private": False,
                            "incoming": True,
                            "body": "Customer inquiry resolved during webhook maintenance window.",
                            "created_at": "2026-10-29T09:00:00Z",
                        }
                    ],
                }
            }

            # First sync run: ingests 1 new ticket
            sync_res_1 = await client.post(
                f"/api/v1/integrations/{created_integration_id}/sync",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"tickets": [backfill_ticket_payload]},
            )
            assert sync_res_1.status_code == 200
            sync_data_1 = sync_res_1.json()
            assert sync_data_1["status"] == "COMPLETED"
            assert sync_data_1["newly_ingested_count"] == 1
            assert sync_data_1["skipped_existing_count"] == 0
            assert sync_data_1["last_successful_sync_at"] is not None

            # Second sync run with same ticket: skips existing record (0 newly ingested)
            sync_res_2 = await client.post(
                f"/api/v1/integrations/{created_integration_id}/sync",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"tickets": [backfill_ticket_payload]},
            )
            assert sync_res_2.status_code == 200
            sync_data_2 = sync_res_2.json()
            assert sync_data_2["newly_ingested_count"] == 0
            assert sync_data_2["skipped_existing_count"] == 1
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(Ticket).where(
                        Ticket.external_ticket_id == sync_ticket_id
                    )
                )
                if created_integration_id:
                    await db.execute(
                        delete(Integration).where(
                            Integration.id == uuid.UUID(created_integration_id)
                        )
                    )
                await db.commit()
