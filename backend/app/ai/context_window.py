from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import tiktoken

from app.core.config import settings

HEAD_VERBATIM_TURNS = 4
TAIL_VERBATIM_TURNS = 8
MIDDLE_CHUNK_TOKEN_LIMIT = 4000

_SUBWORD_FALLBACK_RE = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)


@lru_cache(maxsize=1)
def _get_cl100k_encoding() -> Optional[tiktoken.Encoding]:
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """
    Estimate token count using `tiktoken` (`cl100k_base` approximation per Section 1.3 & 3.4).
    Falls back to subword regex tokenization if the BPE vocabulary is unavailable offline.
    """
    if not text:
        return 0
    encoding = _get_cl100k_encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    return len(_SUBWORD_FALLBACK_RE.findall(text))


def _format_utc_timestamp(raw_ts: Any) -> str:
    if isinstance(raw_ts, datetime):
        dt = (
            raw_ts.astimezone(timezone.utc)
            if raw_ts.tzinfo
            else raw_ts.replace(tzinfo=timezone.utc)
        )
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    if isinstance(raw_ts, str) and raw_ts.strip():
        cleaned = raw_ts.strip()
        iso_candidate = (
            cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
        )
        try:
            dt = datetime.fromisoformat(iso_candidate)
            dt = (
                dt.astimezone(timezone.utc)
                if dt.tzinfo
                else dt.replace(tzinfo=timezone.utc)
            )
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return cleaned

    return "UNKNOWN UTC"


def format_single_turn(turn_number: int, message: Dict[str, Any]) -> str:
    """Format a single transcript message turn as `[Turn #N | YYYY-MM-DD HH:MM UTC | ROLE]: content`."""
    ts_str = _format_utc_timestamp(
        message.get("timestamp") or message.get("created_at")
    )
    role_str = str(message.get("sender_role") or "CUSTOMER").strip().upper()
    content_str = str(message.get("content") or message.get("body") or "").strip()
    return f"[Turn #{turn_number} | {ts_str} | {role_str}]: {content_str}"


def format_transcript_turns(
    messages: List[Dict[str, Any]],
    start_turn_number: int = 1,
) -> str:
    """Format a list of transcript turns with chronological timestamps and 1-based turn indices."""
    lines = [
        format_single_turn(start_turn_number + idx, msg)
        for idx, msg in enumerate(messages)
    ]
    return "\n".join(lines)


def chunk_middle_turns(
    middle_messages: List[Dict[str, Any]],
    start_turn_number: int = 5,
    chunk_token_limit: int = MIDDLE_CHUNK_TOKEN_LIMIT,
) -> List[str]:
    """
    Split the Middle Segment (Turns 5 to N-8) into windows of up to `chunk_token_limit` (4,000) tokens.
    """
    if not middle_messages:
        return []

    chunks: List[str] = []
    current_lines: List[str] = []
    current_tokens = 0

    for idx, msg in enumerate(middle_messages):
        formatted_line = format_single_turn(start_turn_number + idx, msg)
        line_tokens = count_tokens(formatted_line)

        if current_lines and (current_tokens + line_tokens > chunk_token_limit):
            chunks.append("\n".join(current_lines))
            current_lines = [formatted_line]
            current_tokens = line_tokens
        else:
            current_lines.append(formatted_line)
            current_tokens += line_tokens

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


async def default_middle_chunk_summarizer(chunk_text: str) -> str:
    """
    Deterministic extractive compressor preserving:
    (a) troubleshooting steps attempted,
    (b) commitments made by the agent, and
    (c) verbatim quotes demonstrating poor tone or frustration.
    """
    lines = [ln.strip() for ln in chunk_text.splitlines() if ln.strip()]
    if not lines:
        return ""

    preserved_highlights: List[str] = []
    signal_keywords = (
        "tried",
        "tested",
        "restarted",
        "reset",
        "error",
        "failed",
        "will ",
        "promise",
        "escalat",
        "unacceptable",
        "frustrat",
        "ridiculous",
        "useless",
        "closed",
    )

    for line in lines:
        lower_line = line.lower()
        if any(kw in lower_line for kw in signal_keywords):
            # Keep concise snippet of high-signal turn (up to 180 chars)
            preserved_highlights.append(line[:180])
        if len(preserved_highlights) >= 5:
            break

    if not preserved_highlights:
        first_turn = lines[0][:160]
        last_turn = lines[-1][:160] if len(lines) > 1 else ""
        preserved_highlights = (
            [first_turn, last_turn] if last_turn else [first_turn]
        )

    return (
        f"Compressed {len(lines)} middle turns. Key troubleshooting/commitment/tone events: "
        + " ; ".join(preserved_highlights)
    )


async def prepare_transcript_for_evaluation(
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    summarizer_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> Tuple[str, bool]:
    """
    Section 3.4 Stage 2: Hierarchical Head-Body-Tail Windowing (Threshold: 10,000 Tokens).
    - If `count_tokens(formatted) <= max_tokens`: returns `(formatted_transcript, False)` verbatim.
    - If `count_tokens(formatted) > max_tokens`:
      * Head Segment (First 4 Turns — Verbatim)
      * Middle Segment (Turns 5 to N-8 — Chunked into 4,000-token windows & compressed)
      * Tail Segment (Final 8 Turns — Verbatim)
      Returns `(combined_transcript, True)`.
    """
    threshold = (
        max_tokens
        if max_tokens is not None
        else settings.TRANSCRIPT_MAX_VERBATIM_TOKENS
    )
    full_formatted = format_transcript_turns(messages, start_turn_number=1)
    total_tokens = count_tokens(full_formatted)

    if total_tokens <= threshold:
        return full_formatted, False

    active_summarizer = summarizer_fn or default_middle_chunk_summarizer
    total_turns = len(messages)

    # If transcript has >12 turns, use standard Head (first 4) + Middle (5..N-8) + Tail (final 8)
    if total_turns > (HEAD_VERBATIM_TURNS + TAIL_VERBATIM_TURNS):
        head_msgs = messages[:HEAD_VERBATIM_TURNS]
        middle_msgs = messages[HEAD_VERBATIM_TURNS : total_turns - TAIL_VERBATIM_TURNS]
        tail_msgs = messages[total_turns - TAIL_VERBATIM_TURNS :]
        tail_start_turn = total_turns - TAIL_VERBATIM_TURNS + 1

        head_text = format_transcript_turns(head_msgs, start_turn_number=1)
        tail_text = format_transcript_turns(
            tail_msgs, start_turn_number=tail_start_turn
        )

        middle_chunks = chunk_middle_turns(
            middle_msgs,
            start_turn_number=HEAD_VERBATIM_TURNS + 1,
            chunk_token_limit=MIDDLE_CHUNK_TOKEN_LIMIT,
        )
        compressed_chunks: List[str] = []
        for idx, chunk in enumerate(middle_chunks):
            summary_str = await active_summarizer(chunk)
            compressed_chunks.append(
                f"[Compressed Middle Window #{idx + 1}]: {summary_str}"
            )

        middle_summary_block = (
            f"--- [MIDDLE SEGMENT COMPRESSED: Turns #{HEAD_VERBATIM_TURNS + 1} "
            f"to #{total_turns - TAIL_VERBATIM_TURNS}] ---\n"
            + "\n".join(compressed_chunks)
            + "\n--- [END COMPRESSED MIDDLE SEGMENT] ---"
        )

        combined = f"{head_text}\n{middle_summary_block}\n{tail_text}"
        return combined, True

    # Edge case: <= 12 turns but single massive turns exceed threshold
    compressed_summary = await active_summarizer(full_formatted)
    return f"[Compressed Oversized Transcript]: {compressed_summary}", True

