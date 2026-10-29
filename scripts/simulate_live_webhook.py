#!/usr/bin/env python3
"""
Live E2E Webhook Simulator & AI QA Demo Script (`scripts/simulate_live_webhook.py`)

Reads the active Zendesk integration from PostgreSQL, computes a real-time
HMAC-SHA256 `X-Zendesk-Webhook-Signature` + UTC timestamp, and dispatches two
closed support tickets to the live FastAPI Webhook Ingestion endpoint
(`POST http://localhost:8000/api/v1/webhooks/zendesk/{integration_id}`):
  1. A Prematurely Closed technical support ticket (flagged in red on Manager Dashboard).
  2. A Properly Resolved, High-Empathy billing ticket (high QA score report).

After the sub-50ms `202 Accepted` webhook ingestion completes, this script ensures
the AI QA evaluation pipeline (`evaluate_and_persist_ticket`) has finished evaluating
both tickets and prints the direct Next.js dashboard URLs for immediate inspection.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx
from sqlalchemy import select

# Ensure `backend/` is on sys.path when invoked from the repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.crypto import decrypt_secret  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.enums import CrmType, ProcessingStatus  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.services.evaluation_service import evaluate_and_persist_ticket  # noqa: E402


FASTAPI_BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def compute_zendesk_hmac_signature(raw_body: bytes, timestamp_str: str, secret: str) -> str:
    """Compute Base64(HMAC-SHA256(timestamp + raw_body, secret)) for Zendesk webhooks."""
    signing_input = timestamp_str.encode("utf-8") + raw_body
    digest = hmac.new(
        secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


async def resolve_active_zendesk_integration() -> Tuple[str, str]:
    """Fetch the active Zendesk integration ID and decrypted webhook secret from PostgreSQL."""
    async with AsyncSessionLocal() as db:
        stmt = select(Integration).where(
            Integration.crm_type == CrmType.ZENDESK,
            Integration.is_active.is_(True),
        )
        integration = (await db.execute(stmt)).scalars().first()
        if integration is None:
            raise RuntimeError(
                "No active ZENDESK integration found in PostgreSQL. Run `cd frontend && npm run db:seed` first."
            )
        decrypted_secret = decrypt_secret(integration.encrypted_webhook_secret)
        return str(integration.id), decrypted_secret


def build_demo_webhook_payloads() -> list[Dict[str, Any]]:
    """Build two realistic Zendesk closed ticket webhook payloads."""
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = now_utc.strftime("%H%M%S")

    created_1 = (now_utc - timedelta(minutes=42)).strftime("%Y-%m-%dT%H:%M:%SZ")
    turn_1a = (now_utc - timedelta(minutes=41)).strftime("%Y-%m-%dT%H:%M:%SZ")
    turn_1b = (now_utc - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    turn_1c = (now_utc - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    closed_1 = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    created_2 = (now_utc - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    turn_2a = (now_utc - timedelta(minutes=29)).strftime("%Y-%m-%dT%H:%M:%SZ")
    turn_2b = (now_utc - timedelta(minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    turn_2c = (now_utc - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    closed_2 = (now_utc + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    premature_ticket_id = f"ZD-LIVE-PREMATURE-{suffix}"
    exemplary_ticket_id = f"ZD-LIVE-RESOLVED-{suffix}"

    return [
        {
            "label": "1. Prematurely Closed Technical Support Ticket (Red Alert Demo)",
            "external_ticket_id": premature_ticket_id,
            "payload": {
                "ticket": {
                    "id": premature_ticket_id,
                    "status": "closed",
                    "subject": "Production SSO SAML 2.0 assertion signature failure (Error 500)",
                    "priority": "urgent",
                    "via": {"channel": "web"},
                    "assignee_id": "zd_agent_102",
                    "Assignee": {
                        "id": "zd_agent_102",
                        "name": "Omar Hassan",
                        "email": "omar.agent@qa-platform.local",
                    },
                    "requester_id": "cust_enterprise_okta_99",
                    "created_at": created_1,
                    "updated_at": closed_1,
                    "tags": ["sso", "saml", "production_outage", "live_demo"],
                    "comments": [
                        {
                            "id": f"msg_{suffix}_101",
                            "author_id": "cust_enterprise_okta_99",
                            "author_name": "Elena Rostova (VP Engineering)",
                            "role": "end-user",
                            "public": True,
                            "body": (
                                "URGENT: Our entire engineering organization is locked out after rotating "
                                "our Okta SAML 2.0 signing certificate. Every login attempt returns "
                                "HTTP 500 SAML Signature Verification Failed."
                            ),
                            "created_at": turn_1a,
                        },
                        {
                            "id": f"msg_{suffix}_102",
                            "author_id": "zd_agent_102",
                            "author_name": "Omar Hassan",
                            "role": "agent",
                            "public": True,
                            "body": (
                                "Please clear your browser cookies and try logging in again. "
                                "Closing this ticket as resolved for now."
                            ),
                            "created_at": turn_1b,
                        },
                        {
                            "id": f"msg_{suffix}_103",
                            "author_id": "cust_enterprise_okta_99",
                            "author_name": "Elena Rostova (VP Engineering)",
                            "role": "end-user",
                            "public": True,
                            "body": (
                                "Wait, clearing cookies does nothing for a server-side SAML certificate mismatch! "
                                "We are still completely locked out and the issue is unresolved — please do not close this ticket!"
                            ),
                            "created_at": turn_1c,
                        },
                    ],
                }
            },
        },
        {
            "label": "2. Properly Resolved, High-Empathy Billing Ticket (High Score Demo)",
            "external_ticket_id": exemplary_ticket_id,
            "payload": {
                "ticket": {
                    "id": exemplary_ticket_id,
                    "status": "closed",
                    "subject": "Duplicate annual enterprise invoice charge after seat upgrade",
                    "priority": "high",
                    "via": {"channel": "email"},
                    "assignee_id": "zd_agent_101",
                    "Assignee": {
                        "id": "zd_agent_101",
                        "name": "Sarah Jenkins",
                        "email": "sarah.agent@qa-platform.local",
                    },
                    "requester_id": "cust_finops_lead_42",
                    "created_at": created_2,
                    "updated_at": closed_2,
                    "tags": ["billing", "refund", "enterprise", "live_demo"],
                    "comments": [
                        {
                            "id": f"msg_{suffix}_201",
                            "author_id": "cust_finops_lead_42",
                            "author_name": "Marcus Vance (FinOps Director)",
                            "role": "end-user",
                            "public": True,
                            "body": (
                                "Hi team, we upgraded from 25 to 40 seats yesterday and noticed two separate "
                                "charges on our corporate card for the full annual amount instead of a prorated invoice."
                            ),
                            "created_at": turn_2a,
                        },
                        {
                            "id": f"msg_{suffix}_202",
                            "author_id": "zd_agent_101",
                            "author_name": "Sarah Jenkins",
                            "role": "agent",
                            "public": True,
                            "body": (
                                "I completely understand how concerning it is to see a duplicate annual charge on your "
                                "corporate statement, and I sincerely apologize for the inconvenience. I have audited your "
                                "billing ledger, voided the duplicate full-year invoice (#INV-2026-8841), issued an immediate "
                                "refund of $4,800.00 to your card, and confirmed only the prorated 15-seat upgrade remains active."
                            ),
                            "created_at": turn_2b,
                        },
                        {
                            "id": f"msg_{suffix}_203",
                            "author_id": "cust_finops_lead_42",
                            "author_name": "Marcus Vance (FinOps Director)",
                            "role": "end-user",
                            "public": True,
                            "body": (
                                "Thank you so much Sarah! I already see the refund notification from our bank and the updated "
                                "prorated invoice in the portal. Really appreciate the fast and thorough resolution!"
                            ),
                            "created_at": turn_2c,
                        },
                    ],
                }
            },
        },
    ]


async def wait_for_ingested_ticket_and_evaluate(external_ticket_id: str) -> Dict[str, Any]:
    """Wait for the background webhook ingestion task to persist the ticket, then run AI QA evaluation."""
    ticket_uuid = None
    for _ in range(30):
        async with AsyncSessionLocal() as db:
            stmt = select(Ticket).where(Ticket.external_ticket_id == external_ticket_id)
            ticket = (await db.execute(stmt)).scalars().first()
            if ticket is not None:
                ticket_uuid = ticket.id
                if ticket.processing_status == ProcessingStatus.EVALUATED:
                    break
                break
        await asyncio.sleep(0.1)

    if ticket_uuid is None:
        raise RuntimeError(f"Timed out waiting for ticket {external_ticket_id} to be persisted.")

    eval_summary = await evaluate_and_persist_ticket(
        ticket_id=ticket_uuid,
        bypass_rate_limit=True,
    )
    return eval_summary


async def main() -> None:
    print("=" * 88)
    print("  LIVE E2E WEBHOOK SIMULATOR — Customer Support Ticket Summarization & Agent QA Platform")
    print("=" * 88)

    integration_id, webhook_secret = await resolve_active_zendesk_integration()
    webhook_url = f"{FASTAPI_BASE_URL}/api/v1/webhooks/zendesk/{integration_id}"
    print(f"• Active Zendesk Integration ID : {integration_id}")
    print(f"• Target Webhook Endpoint       : POST {webhook_url}\n")

    demo_cases = build_demo_webhook_payloads()

    async with httpx.AsyncClient(timeout=15.0) as client:
        for case in demo_cases:
            label = case["label"]
            ext_id = case["external_ticket_id"]
            raw_body = json.dumps(case["payload"]).encode("utf-8")
            timestamp_str = str(int(time.time()))
            signature = compute_zendesk_hmac_signature(raw_body, timestamp_str, webhook_secret)

            headers = {
                "Content-Type": "application/json",
                "X-Zendesk-Webhook-Signature": signature,
                "X-Zendesk-Webhook-Signature-Timestamp": timestamp_str,
            }

            t0 = time.perf_counter()
            response = await client.post(webhook_url, content=raw_body, headers=headers)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            resp_data = response.json()
            eval_result = await wait_for_ingested_ticket_and_evaluate(ext_id)
            ticket_uuid = eval_result["ticket_id"]

            print(f"--- {label} ---")
            print(f"  External Ticket ID       : {ext_id}")
            print(f"  Webhook HTTP Status      : {response.status_code} ({resp_data.get('status')})")
            print(f"  Webhook Ingestion Latency: {latency_ms:.2f} ms")
            print(f"  Ingestion Job ID         : {resp_data.get('job_id')}")
            print(f"  AI QA Overall Score      : {eval_result['agent_score']} / 100")
            print(f"  Resolution Status        : {eval_result['resolution_status']}")
            print(f"  Premature Closure Alert  : {eval_result['premature_closure_detected']}")
            print(f"  Direct 3-Pane Review URL : {FRONTEND_BASE_URL}/manager/tickets/{ticket_uuid}\n")

    print("=" * 88)
    print(f"  All 2 live tickets ingested & evaluated! Open {FRONTEND_BASE_URL}/manager/tickets")
    print("=" * 88)


if __name__ == "__main__":
    asyncio.run(main())

