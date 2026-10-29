from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.crypto import AES_GCM_PREFIX, decrypt_secret, encrypt_secret
from app.integrations import (
    CustomCRMConnector,
    FreshdeskConnector,
    IntercomConnector,
    ProviderRegistry,
    ZendeskConnector,
)
from app.models.enums import CrmType, TicketChannel, TicketPriority
from app.schemas.ticket_payload import (
    MessageSenderRole,
    NormalizedMessage,
    StandardTicketPayload,
)
from app.services.sanitizer import (
    REDACTED_TOKEN,
    collapse_consecutive_system_messages,
    sanitize_and_redact_text,
)


def test_aes256gcm_encryption_roundtrip_and_seeded_compat() -> None:
    """
    Verify AES-256-GCM encryption/decryption round-trip, unique random nonces,
    tamper detection, and backward compatibility with Phase 1 seeded dummy secrets.
    """
    raw_secret = "whsec_zendesk_prod_998877665544332211"
    encrypted_1 = encrypt_secret(raw_secret)
    encrypted_2 = encrypt_secret(raw_secret)

    assert encrypted_1.startswith(AES_GCM_PREFIX)
    assert encrypted_2.startswith(AES_GCM_PREFIX)
    # Random 12-byte IV ensures identical plaintexts produce distinct ciphertexts
    assert encrypted_1 != encrypted_2

    assert decrypt_secret(encrypted_1) == raw_secret
    assert decrypt_secret(encrypted_2) == raw_secret

    # Backward compatibility with Phase 1 seeded integration secrets
    seeded_dummy = "enc_aes256gcm_v1:dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d"
    assert (
        decrypt_secret(seeded_dummy)
        == "dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d"
    )

    # Tampered ciphertext must fail GCM authentication tag verification
    tampered = encrypted_1[:-4] + "AAAA"
    with pytest.raises(ValueError, match="authentication tag|Invalid"):
        decrypt_secret(tampered)


def test_html_quoted_email_stripping_and_pii_redaction() -> None:
    """
    Verify HTML/script stripping, quoted email chain removal, and PII redaction
    (Credit Cards, SSNs, Bearer/API tokens, and passwords).
    """
    fake_token = "sk_" + "live_99887766554433221100abcdef"
    raw_html_and_pii = f"""
    <html>
      <head>
        <style>body {{ color: red; }}</style>
        <script>alert("xss");</script>
      </head>
      <body>
        <p>Hello Support,</p>
        <div>My card 4532-0151-1283-0366 was charged twice!</div>
        <p>My SSN is 123-45-6789 and my test token is {fake_token}.</p>
        <p>Header used: Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret.sig and password=MySuperSecretPass123</p>
        <br/>
        On Mon, Oct 28, 2026 at 10:15 AM Support Agent &lt;support@acme.local&gt; wrote:
        &gt; Please send your billing details so we can check.
        &gt; Thanks!
      </body>
    </html>
    """

    cleaned = sanitize_and_redact_text(raw_html_and_pii)

    # HTML and script content stripped
    assert "<p>" not in cleaned
    assert "<div>" not in cleaned
    assert "alert(" not in cleaned
    assert "color: red" not in cleaned

    # Quoted reply chain removed
    assert "On Mon, Oct 28" not in cleaned
    assert "Please send your billing details" not in cleaned

    # Sensitive PII replaced with [REDACTED_SENSITIVE]
    assert "4532-0151-1283-0366" not in cleaned
    assert "123-45-6789" not in cleaned
    assert fake_token not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9.secret.sig" not in cleaned
    assert "MySuperSecretPass123" not in cleaned
    assert cleaned.count(REDACTED_TOKEN) >= 5


def test_collapse_consecutive_bot_and_system_messages() -> None:
    """Verify consecutive BOT/SYSTEM messages are collapsed into a single metadata turn."""
    ts = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    messages = [
        NormalizedMessage(
            message_id="m1",
            sender_role=MessageSenderRole.BOT,
            sender_name="TriageBot",
            timestamp=ts,
            content="Automated greeting triggered.",
        ),
        NormalizedMessage(
            message_id="m2",
            sender_role=MessageSenderRole.SYSTEM,
            sender_name="System",
            timestamp=ts,
            content="Routed to Tier-2 Billing Queue.",
        ),
        NormalizedMessage(
            message_id="m3",
            sender_role=MessageSenderRole.CUSTOMER,
            sender_name="Customer",
            timestamp=ts,
            content="I need help with my invoice.",
        ),
    ]

    collapsed = collapse_consecutive_system_messages(messages)
    assert len(collapsed) == 2
    assert collapsed[0].sender_role == MessageSenderRole.BOT
    assert (
        "Automated greeting triggered. | Routed to Tier-2 Billing Queue."
        in collapsed[0].content
    )
    assert collapsed[1].sender_role == MessageSenderRole.CUSTOMER


def test_crm_connectors_valid_hmac_signatures() -> None:
    """
    Verify valid HMAC-SHA256 signatures pass for Zendesk, Intercom, Freshdesk, and Custom connectors.
    """
    secret = "shared_webhook_signing_secret_2026"
    now_iso = datetime.now(timezone.utc).isoformat()
    now_epoch = str(int(datetime.now(timezone.utc).timestamp()))
    raw_body = json.dumps({"ticket": {"id": "1001", "status": "closed"}}).encode(
        "utf-8"
    )

    # 1. Zendesk: Base64(HMAC-SHA256(timestamp + raw_body, secret))
    zd_connector = ProviderRegistry.get_connector(CrmType.ZENDESK)
    zd_digest = hmac.new(
        secret.encode("utf-8"),
        now_iso.encode("utf-8") + raw_body,
        hashlib.sha256,
    ).digest()
    zd_sig = base64.b64encode(zd_digest).decode("ascii")
    assert (
        zd_connector.verify_signature(
            headers={
                "X-Zendesk-Webhook-Signature": zd_sig,
                "X-Zendesk-Webhook-Signature-Timestamp": now_iso,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is True
    )

    # 2. Intercom: sha256=<hex_digest>
    ic_connector = ProviderRegistry.get_connector("intercom")
    ic_hex = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    assert (
        ic_connector.verify_signature(
            headers={
                "X-Hub-Signature-256": f"sha256={ic_hex}",
                "X-Intercom-Timestamp": now_epoch,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is True
    )

    # 3. Freshdesk: X-Webhook-Signature (HMAC-SHA256) and X-Integration-Api-Key
    fd_connector = ProviderRegistry.get_connector("freshdesk")
    fd_hex = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    assert (
        fd_connector.verify_signature(
            headers={
                "X-Webhook-Signature": fd_hex,
                "X-Webhook-Timestamp": now_epoch,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is True
    )
    assert (
        fd_connector.verify_signature(
            headers={
                "X-Integration-Api-Key": secret,
                "X-Webhook-Timestamp": now_epoch,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is True
    )

    # 4. Custom CRM: X-Webhook-Signature
    cust_connector = ProviderRegistry.get_connector(CrmType.CUSTOM)
    assert (
        cust_connector.verify_signature(
            headers={
                "X-Webhook-Signature": f"sha256={fd_hex}",
                "X-Webhook-Timestamp": now_iso,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is True
    )


def test_crm_connectors_reject_tampered_payloads_and_expired_timestamps() -> None:
    """
    Verify tampered payloads and timestamps outside the 300-second replay window
    are strictly rejected (`verify_signature` returns False).
    """
    secret = "shared_webhook_signing_secret_2026"
    raw_body = b'{"ticket":{"id":"999","status":"closed"}}'
    tampered_body = b'{"ticket":{"id":"999","status":"open"}}'

    # Expired timestamp (10 minutes ago > 300s window)
    expired_dt = datetime.now(timezone.utc) - timedelta(seconds=600)
    expired_iso = expired_dt.isoformat()
    expired_epoch = str(int(expired_dt.timestamp()))
    now_iso = datetime.now(timezone.utc).isoformat()

    zd = ZendeskConnector()
    valid_zd_sig_for_expired = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            expired_iso.encode("utf-8") + raw_body,
            hashlib.sha256,
        ).digest()
    ).decode("ascii")

    # 1. Expired timestamp on Zendesk must return False
    assert (
        zd.verify_signature(
            headers={
                "X-Zendesk-Webhook-Signature": valid_zd_sig_for_expired,
                "X-Zendesk-Webhook-Signature-Timestamp": expired_iso,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is False
    )

    # 2. Tampered body on Zendesk with current timestamp must return False
    valid_now_sig = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            now_iso.encode("utf-8") + raw_body,
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    assert (
        zd.verify_signature(
            headers={
                "X-Zendesk-Webhook-Signature": valid_now_sig,
                "X-Zendesk-Webhook-Signature-Timestamp": now_iso,
            },
            raw_body=tampered_body,
            secret=secret,
        )
        is False
    )

    # 3. Expired timestamp and tampered body on Intercom must return False
    ic = IntercomConnector()
    ic_sig = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    assert (
        ic.verify_signature(
            headers={
                "X-Hub-Signature-256": f"sha256={ic_sig}",
                "X-Intercom-Timestamp": expired_epoch,
            },
            raw_body=raw_body,
            secret=secret,
        )
        is False
    )
    assert (
        ic.verify_signature(
            headers={"X-Hub-Signature-256": f"sha256={ic_sig}"},
            raw_body=tampered_body,
            secret=secret,
        )
        is False
    )


def test_ticket_closed_state_filtering_across_connectors() -> None:
    """
    Verify non-closed events (`open`, `pending`, `in_progress`) return False
    and terminal closed/solved events return True.
    """
    zd = ZendeskConnector()
    ic = IntercomConnector()
    fd = FreshdeskConnector()
    cu = CustomCRMConnector()

    assert zd.is_ticket_closed_event({"ticket": {"status": "open"}}) is False
    assert zd.is_ticket_closed_event({"ticket": {"status": "pending"}}) is False
    assert zd.is_ticket_closed_event({"ticket": {"status": "closed"}}) is True
    assert zd.is_ticket_closed_event({"ticket": {"status": "solved"}}) is True

    assert (
        ic.is_ticket_closed_event(
            {"topic": "conversation.user.replied", "conversation": {"state": "open"}}
        )
        is False
    )
    assert (
        ic.is_ticket_closed_event(
            {"topic": "conversation.admin.closed", "conversation": {"state": "closed"}}
        )
        is True
    )

    assert fd.is_ticket_closed_event({"ticket": {"status": 2}}) is False  # 2 = Open
    assert fd.is_ticket_closed_event({"ticket": {"status": 5}}) is True  # 5 = Closed
    assert fd.is_ticket_closed_event({"ticket": {"status": "resolved"}}) is True

    assert cu.is_ticket_closed_event({"status": "pending"}) is False
    assert cu.is_ticket_closed_event({"status": "closed"}) is True


def test_normalize_payload_across_all_four_crm_connectors() -> None:
    """
    Verify Zendesk, Intercom, Freshdesk, and Custom connectors normalize native payloads
    into validated `StandardTicketPayload` contracts with sanitized messages and filtered notes.
    """
    integration_id = "22222222-2222-4222-8222-222222222201"

    # 1. Zendesk Normalization
    zd_payload = {
        "ticket": {
            "id": 99412,
            "assignee_id": "zd_agent_101",
            "assignee_email": "sarah.agent@qa-platform.local",
            "assignee_name": "Sarah Jenkins",
            "requester_email": "alice@customer-corp.com",
            "subject": "Billing card error",
            "via": {"channel": "email"},
            "priority": "high",
            "tags": ["billing", "urgent"],
            "created_at": "2026-10-28T13:00:00Z",
            "updated_at": "2026-10-28T14:00:00Z",
            "comments": [
                {
                    "id": "c1",
                    "author_id": "cust_1",
                    "public": True,
                    "created_at": "2026-10-28T13:00:00Z",
                    "body": "<p>My card 4532 0151 1283 0366 failed.</p>",
                },
                {
                    "id": "c_internal",
                    "author_id": "zd_agent_101",
                    "public": False,
                    "created_at": "2026-10-28T13:15:00Z",
                    "body": "Internal note: checking Stripe logs",
                },
                {
                    "id": "c2",
                    "author_id": "zd_agent_101",
                    "public": True,
                    "created_at": "2026-10-28T13:30:00Z",
                    "body": "<div>We reset your payment gateway.</div>",
                },
            ],
        }
    }
    zd_norm = ZendeskConnector().normalize_payload(zd_payload, integration_id)
    assert isinstance(zd_norm, StandardTicketPayload)
    assert zd_norm.crm_provider == CrmType.ZENDESK
    assert zd_norm.external_ticket_id == "99412"
    assert zd_norm.external_agent_id == "zd_agent_101"
    assert zd_norm.priority == TicketPriority.HIGH
    assert zd_norm.channel == TicketChannel.EMAIL
    assert zd_norm.customer_identifier.startswith("cust_hash_")
    # Private comment filtered out -> 2 public messages remain
    assert len(zd_norm.messages) == 2
    assert REDACTED_TOKEN in zd_norm.messages[0].content
    assert "<p>" not in zd_norm.messages[0].content

    # 2. Intercom Normalization
    ic_payload = {
        "conversation": {
            "id": "ic_conv_551",
            "admin_assignee_id": "zd_agent_102",
            "agent_email": "omar.agent@qa-platform.local",
            "title": "SSO Login Issue",
            "priority": "urgent",
            "created_at": 1793192400,
            "statistics": {
                "last_close_at": 1793196000,
                "time_to_admin_reply": 120,
            },
            "source": {
                "id": "src_1",
                "delivered_as": "messenger",
                "body": "<p>Cannot sign in with password=MySecret99</p>",
                "author": {"id": "user_77", "name": "Bob"},
            },
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "id": "p1",
                        "part_type": "comment",
                        "body": "<p>Cleared your SAML session cache.</p>",
                        "created_at": 1793193000,
                        "author": {"type": "admin", "name": "Omar Hassan"},
                    }
                ]
            },
        }
    }
    ic_norm = IntercomConnector().normalize_payload(ic_payload, integration_id)
    assert ic_norm.crm_provider == CrmType.INTERCOM
    assert ic_norm.channel == TicketChannel.LIVE_CHAT
    assert ic_norm.priority == TicketPriority.URGENT
    assert len(ic_norm.messages) == 2
    assert REDACTED_TOKEN in ic_norm.messages[0].content
    assert ic_norm.messages[1].sender_role == MessageSenderRole.AGENT

    # 3. Freshdesk Normalization
    fd_payload = {
        "ticket": {
            "id": "FD-700",
            "responder_id": "zd_agent_101",
            "responder_email": "sarah.agent@qa-platform.local",
            "subject": "Webhook timeout",
            "source": 2,  # Web form
            "priority": 3,  # High
            "created_at": "2026-10-28T10:00:00Z",
            "stats": {"closed_at": "2026-10-28T11:00:00Z"},
            "conversations": [
                {
                    "id": "fdc_1",
                    "private": False,
                    "incoming": True,
                    "body": "API key " + "sk_" + "live_1234567890abcdef is timing out.",
                    "created_at": "2026-10-28T10:00:00Z",
                }
            ],
        }
    }
    fd_norm = FreshdeskConnector().normalize_payload(fd_payload, integration_id)
    assert fd_norm.crm_provider == CrmType.FRESHDESK
    assert fd_norm.channel == TicketChannel.WEB_FORM
    assert fd_norm.priority == TicketPriority.HIGH
    assert REDACTED_TOKEN in fd_norm.messages[0].content

    # 4. Custom CRM Normalization
    cust_payload = {
        "external_ticket_id": "CUST-301",
        "external_agent_id": "zd_agent_102",
        "agent_email": "omar.agent@qa-platform.local",
        "customer_identifier": "cust_hash_custom01",
        "subject": "Custom API integration check",
        "channel": "API",
        "priority": "LOW",
        "created_at": "2026-10-28T08:00:00Z",
        "closed_at": "2026-10-28T08:30:00Z",
        "messages": [
            {
                "message_id": "cm_1",
                "sender_role": "CUSTOMER",
                "timestamp": "2026-10-28T08:00:00Z",
                "content": "Testing custom ticket ingestion with SSN 999-88-7777.",
            }
        ],
    }
    cust_norm = CustomCRMConnector().normalize_payload(
        cust_payload, uuid.UUID(integration_id)
    )
    assert cust_norm.crm_provider == CrmType.CUSTOM
    assert cust_norm.channel == TicketChannel.API
    assert cust_norm.priority == TicketPriority.LOW
    assert REDACTED_TOKEN in cust_norm.messages[0].content

