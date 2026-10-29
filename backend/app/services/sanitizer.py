from __future__ import annotations

import html
import re
from typing import List

from app.schemas.ticket_payload import MessageSenderRole, NormalizedMessage

REDACTED_TOKEN = "[REDACTED_SENSITIVE]"

# 1. HTML & Base64 Boilerplate Patterns
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_DATA_IMAGE_URI_RE = re.compile(
    r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+",
    flags=re.IGNORECASE,
)
_BLOCK_BREAK_TAG_RE = re.compile(
    r"</?(?:br|p|div|li|tr|h[1-6]|blockquote)\b[^>]*>",
    flags=re.IGNORECASE,
)
_GENERIC_HTML_TAG_RE = re.compile(r"<[^>]+>")

# 2. Quoted Email Reply History Patterns
_QUOTED_HEADER_SPLITTER_RE = re.compile(
    r"(?:^|\n)\s*On\s+.+?\bwrote:\s*(?:\n.*)?$",
    flags=re.IGNORECASE | re.DOTALL,
)
_ORIGINAL_MESSAGE_SPLITTER_RE = re.compile(
    r"(?:^|\n)\s*-{2,}\s*Original Message\s*-{2,}.*$",
    flags=re.IGNORECASE | re.DOTALL,
)
_QUOTED_LINE_RE = re.compile(r"^\s*>.*$", flags=re.MULTILINE)

# 3. Sensitive PII & Credential Patterns
# Credit Cards: 13-19 digits, optionally grouped by spaces or hyphens
_CREDIT_CARD_RE = re.compile(
    r"\b(?:\d{4}[ -]?){3}\d{1,7}\b|\b\d{4}[ -]\d{6}[ -]\d{5}\b"
)
# US SSN: XXX-XX-XXXX
_SSN_RE = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b|\bSSN\s*[:#]?\s*\d{3}[ -]?\d{2}[ -]?\d{4}\b",
    flags=re.IGNORECASE,
)
# Bearer tokens
_BEARER_TOKEN_RE = re.compile(
    r"\b(Bearer\s+)[A-Za-z0-9\-._~+/]+=*",
    flags=re.IGNORECASE,
)
# Known API token prefixes (Stripe, GitHub, Slack, OpenAI, Groq, Google, AWS)
_PREFIXED_API_TOKEN_RE = re.compile(
    r"\b(?:sk_live_|sk_test_|pk_live_|pk_test_|rk_live_|ghp_|gho_|github_pat_|xoxb-|xoxp-|gsk_|AIza|AKIA)[A-Za-z0-9_\-]{8,}\b"
)
# Key-value API keys, secrets, tokens
_KV_SECRET_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|client[_-]?secret|webhook[_-]?secret)(\s*[:=]\s*[\"']?)([^\s\"',;]+)([\"']?)",
    flags=re.IGNORECASE,
)
# Key-value passwords
_PASSWORD_RE = re.compile(
    r"\b(password|passwd|pwd)(\s*[:=]\s*[\"']?)([^\s\"',;]+)([\"']?)",
    flags=re.IGNORECASE,
)


def sanitize_and_redact_text(raw_content: str) -> str:
    """
    Stage 1 Pre-Processing (Section 3.4):
    1. Strip `<script>`, `<style>`, inline base64 images, and HTML tags.
    2. Strip quoted email reply chains (`On ... wrote:`, `> ...`, `-----Original Message-----`).
    3. Scrub Credit Card numbers, SSNs, Bearer/API tokens, and passwords with `[REDACTED_SENSITIVE]`.
    4. Normalize whitespace cleanly.
    """
    if not raw_content:
        return ""

    text = raw_content

    # Step 1: Strip script/style blocks, comments, and inline base64 images
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _DATA_IMAGE_URI_RE.sub(REDACTED_TOKEN, text)

    # Convert block-level HTML tags to newlines before stripping remaining tags
    text = _BLOCK_BREAK_TAG_RE.sub("\n", text)
    text = _GENERIC_HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)

    # Step 2: Strip quoted email history
    text = _ORIGINAL_MESSAGE_SPLITTER_RE.sub("", text)
    text = _QUOTED_HEADER_SPLITTER_RE.sub("", text)
    text = _QUOTED_LINE_RE.sub("", text)

    # Step 3: Scrub PII and sensitive credentials
    text = _CREDIT_CARD_RE.sub(REDACTED_TOKEN, text)
    text = _SSN_RE.sub(REDACTED_TOKEN, text)
    text = _BEARER_TOKEN_RE.sub(rf"\1{REDACTED_TOKEN}", text)
    text = _PREFIXED_API_TOKEN_RE.sub(REDACTED_TOKEN, text)
    text = _KV_SECRET_RE.sub(rf"\1\2{REDACTED_TOKEN}\4", text)
    text = _PASSWORD_RE.sub(rf"\1\2{REDACTED_TOKEN}\4", text)

    # Step 4: Normalize horizontal and vertical whitespace
    lines = []
    for raw_line in text.splitlines():
        collapsed_line = re.sub(r"[ \t\r\f\v]+", " ", raw_line).strip()
        if collapsed_line:
            lines.append(collapsed_line)

    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else "[EMPTY_MESSAGE]"


def collapse_consecutive_system_messages(
    messages: List[NormalizedMessage],
) -> List[NormalizedMessage]:
    """
    Stage 1 Pre-Processing (Section 3.4):
    Collapse consecutive automated `BOT` or `SYSTEM` messages into a single metadata turn.
    """
    if not messages:
        return []

    collapsed: List[NormalizedMessage] = []
    automated_roles = {MessageSenderRole.SYSTEM, MessageSenderRole.BOT}

    for msg in messages:
        if (
            collapsed
            and msg.sender_role in automated_roles
            and collapsed[-1].sender_role in automated_roles
        ):
            prev = collapsed[-1]
            merged_content = f"{prev.content} | {msg.content}"
            collapsed[-1] = NormalizedMessage(
                message_id=prev.message_id,
                sender_role=prev.sender_role,
                sender_name=prev.sender_name or msg.sender_name,
                timestamp=prev.timestamp,
                content=merged_content,
                is_internal_note=prev.is_internal_note and msg.is_internal_note,
            )
        else:
            collapsed.append(msg)

    return collapsed

