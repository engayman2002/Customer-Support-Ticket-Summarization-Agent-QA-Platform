from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.ai.context_window import (
    count_tokens,
    default_middle_chunk_summarizer,
    prepare_transcript_for_evaluation,
)
from app.ai.prompts import (
    MIDDLE_SEGMENT_COMPRESSION_SYSTEM_PROMPT,
    build_evaluation_prompt_messages,
)
from app.core.config import settings
from app.models.enums import (
    IssueCategory,
    ResolutionStatus,
    SentimentTrajectory,
)
from app.schemas.qa_evaluation import (
    CoachingPlanItem,
    EvidenceIssueType,
    EvidenceSpeaker,
    FlaggedEvidenceQuote,
    TicketQAEvaluation,
    apply_qa_scoring_guardrails,
)

logger = logging.getLogger(__name__)


@dataclass
class EvaluationExecutionResult:
    """Complete execution result from `GroqTicketEvaluator.evaluate_ticket`."""

    evaluation: TicketQAEvaluation
    model_used: str
    fallback_model_used: bool
    was_compressed: bool
    prompt_tokens: int
    completion_tokens: int
    inference_latency_ms: int


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            if value.tzinfo
            else value.replace(tzinfo=timezone.utc)
        )
    if isinstance(value, str) and value.strip():
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
            return (
                dt.astimezone(timezone.utc)
                if dt.tzinfo
                else dt.replace(tzinfo=timezone.utc)
            )
        except ValueError:
            return None
    return None


def _classify_issue_category(subject: str, full_text: str) -> IssueCategory:
    combined = f"{subject} {full_text}".lower()
    if any(
        kw in combined
        for kw in (
            "refund",
            "invoice",
            "charge",
            "billing",
            "payment",
            "card",
            "receipt",
            "overcharge",
        )
    ):
        return IssueCategory.BILLING
    if any(
        kw in combined
        for kw in (
            "cancel",
            "unsubscribe",
            "close my account",
            "terminate subscription",
            "downgrade",
        )
    ):
        return IssueCategory.CANCELLATION
    if any(
        kw in combined
        for kw in (
            "sso",
            "saml",
            "login",
            "password",
            "2fa",
            "mfa",
            "locked out",
            "sign in",
            "permission",
            "access",
        )
    ):
        return IssueCategory.ACCOUNT_ACCESS
    if any(
        kw in combined
        for kw in (
            "feature request",
            "roadmap",
            "would love to see",
            "enhancement",
            "dark mode",
            "suggestion",
        )
    ):
        return IssueCategory.FEATURE_REQUEST
    if any(
        kw in combined
        for kw in (
            "how do i",
            "how to",
            "where can i find",
            "guide",
            "tutorial",
            "configure",
        )
    ):
        return IssueCategory.HOW_TO
    if any(
        kw in combined
        for kw in (
            "bug",
            "error",
            "500",
            "502",
            "crash",
            "exception",
            "timeout",
            "broken",
            "webhook",
            "api",
            "latency",
        )
    ):
        return IssueCategory.TECHNICAL_BUG
    return IssueCategory.OTHER


def analyze_transcript_deterministically(
    ticket_metadata: Dict[str, Any],
    raw_transcript: List[Dict[str, Any]],
) -> TicketQAEvaluation:
    """
    Deterministic, rubric-faithful transcript analyzer used when `GROQ_API_KEY` is not
    configured in local/CI environments. Strictly implements Section 3.3 detection rules:
    1. Rude / Hostile / Unhelpful Agent Tone (`POOR_TONE` / `UNHELPFUL_RESPONSE`)
    2. Premature Closure Rules (Last-Word Unresolved Question, Drive-By Link Drop,
       <24h Ghost Closure after diagnostic request, Multi-Part Inquiry Neglect)
    3. Complete & Empathetic Resolution scoring
    """
    subject = str(ticket_metadata.get("subject") or "Support Inquiry").strip()
    turns = list(raw_transcript or [])
    all_contents = " ".join(
        str(t.get("content") or t.get("body") or "") for t in turns
    )
    issue_category = _classify_issue_category(subject, all_contents)

    customer_turns = [
        t
        for t in turns
        if str(t.get("sender_role") or "").upper() == "CUSTOMER"
    ]
    agent_turns = [
        t for t in turns if str(t.get("sender_role") or "").upper() == "AGENT"
    ]

    flagged_quotes: List[FlaggedEvidenceQuote] = []
    poor_tone_detected = False
    unhelpful_detected = False

    poor_tone_patterns = (
        "read the manual",
        "if you had read",
        "not my problem",
        "not our problem",
        "stop reopening",
        "stop emailing",
        "stop wasting",
        "waste of our time",
        "waste of time",
        "your own fault",
        "user error, obviously",
        "obviously you",
        "figure it out yourself",
        "do it yourself",
        "already told you",
        "as i already said",
        "incompetent",
        "ridiculous request",
        "stop complaining",
        "i don't care",
        "we don't care",
        "that's your issue",
        "learn how to use",
    )

    unhelpful_patterns = (
        "cannot help you with that, bye",
        "can't help you with that, bye",
        "nothing we can do. closing",
        "no idea why that happens",
        "google it",
        "we don't support this, goodbye",
        "works on my machine",
    )

    for turn in agent_turns:
        content = str(turn.get("content") or turn.get("body") or "").strip()
        lower_c = content.lower()
        if any(pat in lower_c for pat in poor_tone_patterns):
            poor_tone_detected = True
            flagged_quotes.append(
                FlaggedEvidenceQuote(
                    speaker=EvidenceSpeaker.AGENT,
                    quote=content[:280],
                    issue_type=EvidenceIssueType.POOR_TONE,
                )
            )
        elif any(pat in lower_c for pat in unhelpful_patterns):
            unhelpful_detected = True
            flagged_quotes.append(
                FlaggedEvidenceQuote(
                    speaker=EvidenceSpeaker.AGENT,
                    quote=content[:280],
                    issue_type=EvidenceIssueType.UNHELPFUL_RESPONSE,
                )
            )

    # Check Premature Closure Rules (Section 3.3)
    premature_closure = False
    premature_reason: Optional[str] = None

    last_turn = turns[-1] if turns else {}
    last_role = str(last_turn.get("sender_role") or "").upper()
    last_content = str(
        last_turn.get("content") or last_turn.get("body") or ""
    ).strip()
    last_lower = last_content.lower()

    # Rule 1: Last-Word Unresolved Question or Unresolved Statement from CUSTOMER
    unresolved_customer_signals = (
        "?",
        "still not working",
        "still doesn't work",
        "still broken",
        "didn't fix",
        "did not fix",
        "same error",
        "still failing",
        "still getting",
        "wait,",
        "hold on",
        "not resolved",
        "please don't close",
        "nobody answered",
        "hello?",
        "anyone there",
    )
    if last_role == "CUSTOMER" and any(
        sig in last_lower for sig in unresolved_customer_signals
    ):
        premature_closure = True
        premature_reason = (
            "Last-Word Unresolved Inquiry: The final message before closure was from the customer "
            f"reporting an unresolved issue or follow-up question ('{last_content[:120]}')."
        )
        flagged_quotes.append(
            FlaggedEvidenceQuote(
                speaker=EvidenceSpeaker.CUSTOMER,
                quote=last_content[:280],
                issue_type=EvidenceIssueType.PREMATURE_CLOSURE,
            )
        )

    last_agent_content = (
        str(
            agent_turns[-1].get("content") or agent_turns[-1].get("body") or ""
        ).strip()
        if agent_turns
        else ""
    )
    last_agent_lower = last_agent_content.lower()

    # Rule 2: Drive-By Link Drop without resolution verification
    drive_by_signals = (
        "check our faq",
        "read the docs",
        "read our documentation",
        "see this article",
        "here is a link",
        "follow this link",
        "closing this ticket now",
        "marking as solved",
    )
    has_link = "http://" in last_agent_lower or "https://" in last_agent_lower
    has_verification = any(
        v in last_agent_lower
        for v in (
            "verified",
            "refunded",
            "applied the fix",
            "reset your",
            "provisioned",
            "confirmed",
            "let me know if you need anything else",
        )
    )
    if (
        not premature_closure
        and agent_turns
        and (
            (
                has_link
                and len(last_agent_content) < 180
                and not has_verification
            )
            or (
                any(s in last_agent_lower for s in drive_by_signals)
                and has_link
                and last_role == "AGENT"
            )
        )
    ):
        premature_closure = True
        premature_reason = (
            "Drive-By Link Drop: The agent dropped a generic documentation link and closed the ticket "
            "without verifying whether it resolved the customer's specific blocking issue."
        )
        flagged_quotes.append(
            FlaggedEvidenceQuote(
                speaker=EvidenceSpeaker.AGENT,
                quote=last_agent_content[:280],
                issue_type=EvidenceIssueType.PREMATURE_CLOSURE,
            )
        )

    # Rule 3: Ghost Closure without Inactivity Window (<24h after asking customer for info)
    diagnostic_request_signals = (
        "can you send",
        "could you send",
        "please send",
        "please provide",
        "can you share",
        "could you share",
        "send a screenshot",
        "attach the logs",
        "what error code",
        "which browser",
        "can you clarify",
    )
    if (
        not premature_closure
        and last_role == "AGENT"
        and any(sig in last_agent_lower for sig in diagnostic_request_signals)
    ):
        last_agent_ts = _parse_iso_datetime(
            agent_turns[-1].get("timestamp")
            or agent_turns[-1].get("created_at")
        )
        closed_ts = _parse_iso_datetime(ticket_metadata.get("closed_at"))
        hours_waited = 0.0
        if last_agent_ts and closed_ts:
            hours_waited = max(
                0.0, (closed_ts - last_agent_ts).total_seconds() / 3600.0
            )
        if hours_waited < 24.0:
            premature_closure = True
            premature_reason = (
                "Ghost Closure without Inactivity Window: The agent requested diagnostic information "
                f"from the customer and closed the ticket after only {hours_waited:.1f} hours (< 24h threshold)."
            )
            flagged_quotes.append(
                FlaggedEvidenceQuote(
                    speaker=EvidenceSpeaker.AGENT,
                    quote=last_agent_content[:280],
                    issue_type=EvidenceIssueType.PREMATURE_CLOSURE,
                )
            )

    # Rule 4: Multi-Part Inquiry Neglect
    first_customer_content = (
        str(
            customer_turns[0].get("content")
            or customer_turns[0].get("body")
            or ""
        ).strip()
        if customer_turns
        else ""
    )
    first_cust_lower = first_customer_content.lower()
    all_agent_lower = " ".join(
        str(t.get("content") or t.get("body") or "").lower()
        for t in agent_turns
    )
    multi_part_markers = (
        ("1)" in first_cust_lower and "2)" in first_cust_lower)
        or ("1." in first_cust_lower and "2." in first_cust_lower)
        or ("second question" in first_cust_lower)
        or ("also, how" in first_cust_lower)
        or ("and second," in first_cust_lower)
        or ("two questions" in first_cust_lower)
    )
    ignored_second_part_signals = (
        "what about my second question",
        "you didn't answer my second",
        "only answered one",
        "ignoring the second",
    )
    if not premature_closure and (
        any(
            sig in all_contents.lower() for sig in ignored_second_part_signals
        )
        or (
            multi_part_markers
            and len(all_agent_lower) < 140
            and "both" not in all_agent_lower
            and "second" not in all_agent_lower
            and "2)" not in all_agent_lower
            and "2." not in all_agent_lower
        )
    ):
        premature_closure = True
        premature_reason = (
            "Multi-Part Inquiry Neglect: The customer asked multiple distinct questions, "
            "and the agent closed the ticket after addressing only one part of the inquiry."
        )
        flagged_quotes.append(
            FlaggedEvidenceQuote(
                speaker=EvidenceSpeaker.CUSTOMER,
                quote=first_customer_content[:280],
                issue_type=EvidenceIssueType.IGNORED_QUESTION,
            )
        )

    # Deduplicate quotes up to max_length=4
    flagged_quotes = flagged_quotes[:4]

    # Branch 1: Hostile / Rude or Unhelpful Agent Behavior
    if poor_tone_detected or unhelpful_detected:
        score = 24 if poor_tone_detected else 34
        empathy = 2 if poor_tone_detected else 3
        clarity = 4
        ownership = 2
        res_status = (
            ResolutionStatus.PREMATURELY_CLOSED
            if premature_closure
            else ResolutionStatus.UNRESOLVED
        )
        raw_eval = TicketQAEvaluation(
            summary=(
                f"Customer contacted support regarding '{subject}'. "
                "The assigned agent responded with dismissive, unhelpful, or unprofessional language "
                "and failed to resolve the customer's core problem before ticket closure."
            ),
            core_issue=f"Unresolved customer inquiry regarding {subject[:120]}.",
            issue_category=issue_category,
            resolution_status=res_status,
            is_resolved_properly=False,
            premature_closure_detected=premature_closure,
            premature_closure_reason=premature_reason,
            agent_score=score,
            empathy_rating=empathy,
            clarity_and_accuracy_rating=clarity,
            ownership_and_efficiency_rating=ownership,
            customer_sentiment_trajectory=SentimentTrajectory.DEGRADED,
            strengths=[
                "Acknowledged initial ticket receipt within the queue."
            ],
            areas_for_improvement=[
                "Eliminate dismissive, hostile, or blaming language toward customers.",
                "Take full ownership of troubleshooting instead of deflecting the inquiry.",
                "Confirm complete resolution with the customer before closing the ticket.",
            ],
            flagged_evidence_quotes=flagged_quotes,
            actionable_coaching_plan=[
                CoachingPlanItem(
                    focus_area="Professional Empathy & De-escalation",
                    specific_action=(
                        "Replace defensive or dismissive remarks with empathetic validation and concrete diagnostic steps."
                    ),
                    suggested_phrasing_example=(
                        "I understand how frustrating this issue is—let me check your account configuration right now and walk you through the exact fix."
                    ),
                )
            ],
        )
        return apply_qa_scoring_guardrails(raw_eval)

    # Branch 2: Premature Closure Detected
    if premature_closure:
        raw_eval = TicketQAEvaluation(
            summary=(
                f"Customer opened ticket regarding '{subject}'. "
                f"The ticket was closed prematurely before confirming resolution ({premature_reason})."
            )[:590],
            core_issue=f"Customer sought resolution for {subject[:140]}.",
            issue_category=issue_category,
            resolution_status=ResolutionStatus.PREMATURELY_CLOSED,
            is_resolved_properly=False,
            premature_closure_detected=True,
            premature_closure_reason=premature_reason,
            agent_score=38,
            empathy_rating=5,
            clarity_and_accuracy_rating=5,
            ownership_and_efficiency_rating=3,
            customer_sentiment_trajectory=SentimentTrajectory.UNCHANGED_NEGATIVE,
            strengths=[
                "Responded to the initial ticket thread promptly."
            ],
            areas_for_improvement=[
                "Never close a ticket while a customer question or diagnostic request remains pending.",
                "Address every sub-question in multi-part inquiries before marking the ticket solved.",
            ],
            flagged_evidence_quotes=flagged_quotes,
            actionable_coaching_plan=[
                CoachingPlanItem(
                    focus_area="Confirming Resolution Before Closure",
                    specific_action=(
                        "Verify that every customer question is answered and wait for explicit customer confirmation or the 48-hour inactivity window before closing."
                    ),
                    suggested_phrasing_example=(
                        "I have applied those changes and answered both of your questions—please let me know if that resolves the issue on your end before I close this ticket."
                    ),
                )
            ],
        )
        return apply_qa_scoring_guardrails(raw_eval)

    # Branch 3: Properly Resolved (or Properly Escalated) Ticket
    is_escalated = "escalat" in all_agent_lower and (
        "engineering" in all_agent_lower or "tier 3" in all_agent_lower or "tier-3" in all_agent_lower
    )
    res_status = (
        ResolutionStatus.ESCALATED_PROPERLY
        if is_escalated
        else ResolutionStatus.RESOLVED
    )

    raw_eval = TicketQAEvaluation(
        summary=(
            f"Customer contacted support regarding '{subject}'. "
            "The support agent diagnosed the root cause clearly, provided accurate step-by-step "
            "resolution actions, and confirmed that the customer's issue was completely resolved prior to closure."
        )[:590],
        core_issue=f"Resolution of customer inquiry regarding {subject[:140]}.",
        issue_category=issue_category,
        resolution_status=res_status,
        is_resolved_properly=True,
        premature_closure_detected=False,
        premature_closure_reason=None,
        agent_score=91,
        empathy_rating=9,
        clarity_and_accuracy_rating=9,
        ownership_and_efficiency_rating=9,
        customer_sentiment_trajectory=SentimentTrajectory.IMPROVED,
        strengths=[
            "Validated the customer's context empathetically and took immediate ownership.",
            "Provided clear, accurate troubleshooting steps and verified complete resolution before closure.",
        ],
        areas_for_improvement=[
            "Optionally share a self-service knowledge base reference for future prevention."
        ],
        flagged_evidence_quotes=[],
        actionable_coaching_plan=[
            CoachingPlanItem(
                focus_area="Proactive Self-Service Enablement",
                specific_action=(
                    "Include a direct link to the relevant documentation or dashboard view in the final confirmation note."
                ),
                suggested_phrasing_example=(
                    "Everything is now resolved on your account! For future reference, you can also monitor this directly under Settings > Diagnostics."
                ),
            )
        ],
    )
    return apply_qa_scoring_guardrails(raw_eval)


class GroqTicketEvaluator:
    """
    Section 3.1–3.4 LangChain + `ChatGroq` Structured Output Evaluator with:
    - Hierarchical Head-Body-Tail Context Window Compression (`> 10,000` tokens)
    - Primary Model (`llama-3.3-70b-versatile`) with Exponential Backoff + Jitter
    - Automatic Fallback Model (`llama-3.1-8b-instant`) on `429` / `503` / timeout
    - Deterministic Post-Inference Guardrail Clamping (`apply_qa_scoring_guardrails`)
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        compression_model: Optional[str] = None,
        primary_runnable: Optional[Any] = None,
        fallback_runnable: Optional[Any] = None,
        compression_summarizer: Optional[Callable[[str], Awaitable[str]]] = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.05,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else settings.GROQ_API_KEY
        ).strip()
        self.primary_model = primary_model or settings.GROQ_PRIMARY_MODEL
        self.fallback_model = fallback_model or settings.GROQ_FALLBACK_MODEL
        self.compression_model = (
            compression_model or settings.GROQ_COMPRESSION_MODEL
        )
        self._primary_runnable = primary_runnable
        self._fallback_runnable = fallback_runnable
        self._compression_summarizer = compression_summarizer
        self.max_retries = max(1, int(max_retries))
        self.base_backoff_seconds = max(0.0, float(base_backoff_seconds))

    def _build_chat_groq_structured_runnable(self, model_name: str) -> Any:
        """
        Instantiate `ChatGroq` bound with `.with_structured_output(TicketQAEvaluation, method="json_schema", include_raw=True)`.
        """
        llm = ChatGroq(
            model=model_name,
            api_key=self.api_key,
            temperature=0.0,
            max_tokens=2048,
            timeout=30.0,
            max_retries=1,
        )
        return llm.with_structured_output(
            TicketQAEvaluation,
            method="json_schema",
            include_raw=True,
        )

    async def summarize_middle_chunk(self, chunk_text: str) -> str:
        """
        Summarize a 4,000-token middle transcript window using `settings.GROQ_COMPRESSION_MODEL`
        (`llama-3.1-8b-instant`), falling back to `default_middle_chunk_summarizer` if offline.
        """
        if self._compression_summarizer is not None:
            return await self._compression_summarizer(chunk_text)

        if not self.api_key:
            return await default_middle_chunk_summarizer(chunk_text)

        try:
            compressor_llm = ChatGroq(
                model=self.compression_model,
                api_key=self.api_key,
                temperature=0.0,
                max_tokens=512,
                timeout=20.0,
            )
            messages = [
                SystemMessage(content=MIDDLE_SEGMENT_COMPRESSION_SYSTEM_PROMPT),
                HumanMessage(content=chunk_text),
            ]
            response = await compressor_llm.ainvoke(messages)
            content = getattr(response, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
        except Exception as exc:
            logger.warning(
                "Middle-segment LLM compression failed (%s); falling back to extractive summarizer.",
                exc,
            )

        return await default_middle_chunk_summarizer(chunk_text)

    async def _invoke_single_runnable(
        self,
        runnable: Any,
        messages: List[BaseMessage],
    ) -> Tuple[TicketQAEvaluation, Optional[int], Optional[int]]:
        """
        Invoke a LangChain structured output runnable or callable and extract
        `(TicketQAEvaluation, prompt_tokens, completion_tokens)`.
        """
        if hasattr(runnable, "ainvoke"):
            raw_output = await runnable.ainvoke(messages)
        elif hasattr(runnable, "invoke"):
            maybe_coro = runnable.invoke(messages)
            raw_output = (
                await maybe_coro
                if inspect.isawaitable(maybe_coro)
                else maybe_coro
            )
        elif callable(runnable):
            maybe_coro = runnable(messages)
            raw_output = (
                await maybe_coro
                if inspect.isawaitable(maybe_coro)
                else maybe_coro
            )
        else:
            raise TypeError(f"Unsupported runnable type: {type(runnable)!r}")

        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None

        if isinstance(raw_output, TicketQAEvaluation):
            return raw_output, prompt_tokens, completion_tokens

        if isinstance(raw_output, dict):
            # Handle `include_raw=True` output format: `{"raw": AIMessage, "parsed": TicketQAEvaluation, "parsing_error": ...}`
            if "parsed" in raw_output and raw_output["parsed"] is not None:
                parsed_obj = raw_output["parsed"]
                raw_msg = raw_output.get("raw")
                if raw_msg is not None:
                    usage_meta = getattr(raw_msg, "usage_metadata", None) or {}
                    if isinstance(usage_meta, dict):
                        prompt_tokens = usage_meta.get("input_tokens")
                        completion_tokens = usage_meta.get("output_tokens")
                    resp_meta = getattr(raw_msg, "response_metadata", None) or {}
                    if isinstance(resp_meta, dict) and "token_usage" in resp_meta:
                        tu = resp_meta["token_usage"] or {}
                        prompt_tokens = prompt_tokens or tu.get("prompt_tokens")
                        completion_tokens = completion_tokens or tu.get(
                            "completion_tokens"
                        )
                if isinstance(parsed_obj, TicketQAEvaluation):
                    return parsed_obj, prompt_tokens, completion_tokens
                return (
                    TicketQAEvaluation.model_validate(parsed_obj),
                    prompt_tokens,
                    completion_tokens,
                )

            if raw_output.get("parsing_error") is not None:
                raise ValueError(
                    f"Structured output parsing error: {raw_output['parsing_error']}"
                )

            return (
                TicketQAEvaluation.model_validate(raw_output),
                prompt_tokens,
                completion_tokens,
            )

        raise TypeError(
            f"Unexpected output from structured runnable: {type(raw_output)!r}"
        )

    async def _invoke_with_retries(
        self,
        runnable: Any,
        messages: List[BaseMessage],
        model_label: str,
    ) -> Tuple[TicketQAEvaluation, Optional[int], Optional[int]]:
        """
        Execute `runnable` with exponential backoff + jitter up to `self.max_retries` attempts.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._invoke_single_runnable(runnable, messages)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Groq model '%s' attempt %d/%d failed: %s",
                    model_label,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries and self.base_backoff_seconds > 0:
                    backoff = self.base_backoff_seconds * (2 ** (attempt - 1))
                    jitter = random.uniform(0.0, self.base_backoff_seconds * 0.5)
                    await asyncio.sleep(backoff + jitter)

        assert last_exc is not None
        raise last_exc

    async def evaluate_ticket(
        self,
        ticket_metadata: Dict[str, Any],
        raw_transcript: List[Dict[str, Any]],
    ) -> EvaluationExecutionResult:
        """
        Execute the full Section 3.4 Multi-Stage Evaluation Pipeline:
        1. Context Window Compression (`prepare_transcript_for_evaluation`)
        2. Prompt Assembly (`build_evaluation_prompt_messages`)
        3. Primary LLM (`llama-3.3-70b-versatile`) -> Fallback LLM (`llama-3.1-8b-instant`)
        4. Post-Inference Deterministic Guardrail (`apply_qa_scoring_guardrails`)
        """
        t0 = time.perf_counter()

        formatted_transcript, was_compressed = (
            await prepare_transcript_for_evaluation(
                raw_transcript,
                summarizer_fn=self.summarize_middle_chunk,
            )
        )
        messages = build_evaluation_prompt_messages(
            ticket_metadata=ticket_metadata,
            formatted_transcript=formatted_transcript,
        )

        estimated_prompt_tokens = sum(
            count_tokens(str(m.content)) for m in messages
        )

        has_custom_runnables = (
            self._primary_runnable is not None
            or self._fallback_runnable is not None
        )
        use_live_or_injected_llm = has_custom_runnables or bool(self.api_key)

        if not use_live_or_injected_llm:
            deterministic_eval = analyze_transcript_deterministically(
                ticket_metadata=ticket_metadata,
                raw_transcript=raw_transcript,
            )
            guarded_eval = apply_qa_scoring_guardrails(deterministic_eval)
            elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
            estimated_completion_tokens = count_tokens(
                guarded_eval.model_dump_json()
            )
            return EvaluationExecutionResult(
                evaluation=guarded_eval,
                model_used=self.primary_model,
                fallback_model_used=False,
                was_compressed=was_compressed,
                prompt_tokens=max(1, estimated_prompt_tokens),
                completion_tokens=max(1, estimated_completion_tokens),
                inference_latency_ms=elapsed_ms,
            )

        primary_runnable = (
            self._primary_runnable
            if self._primary_runnable is not None
            else self._build_chat_groq_structured_runnable(self.primary_model)
        )

        try:
            raw_eval, p_tokens, c_tokens = await self._invoke_with_retries(
                primary_runnable,
                messages,
                model_label=self.primary_model,
            )
            guarded_eval = apply_qa_scoring_guardrails(raw_eval)
            elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
            final_prompt_tokens = p_tokens or max(1, estimated_prompt_tokens)
            final_completion_tokens = c_tokens or max(
                1, count_tokens(guarded_eval.model_dump_json())
            )
            return EvaluationExecutionResult(
                evaluation=guarded_eval,
                model_used=self.primary_model,
                fallback_model_used=False,
                was_compressed=was_compressed,
                prompt_tokens=final_prompt_tokens,
                completion_tokens=final_completion_tokens,
                inference_latency_ms=elapsed_ms,
            )
        except Exception as primary_exc:
            logger.warning(
                "Primary model '%s' exhausted retries (%s); switching to fallback model '%s'.",
                self.primary_model,
                primary_exc,
                self.fallback_model,
            )

        fallback_runnable = (
            self._fallback_runnable
            if self._fallback_runnable is not None
            else (
                self._build_chat_groq_structured_runnable(self.fallback_model)
                if self.api_key
                else None
            )
        )

        if fallback_runnable is None:
            raise RuntimeError(
                f"Primary model '{self.primary_model}' failed and no fallback runnable is configured."
            )

        try:
            raw_eval, p_tokens, c_tokens = await self._invoke_with_retries(
                fallback_runnable,
                messages,
                model_label=self.fallback_model,
            )
            guarded_eval = apply_qa_scoring_guardrails(raw_eval)
            elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
            final_prompt_tokens = p_tokens or max(1, estimated_prompt_tokens)
            final_completion_tokens = c_tokens or max(
                1, count_tokens(guarded_eval.model_dump_json())
            )
            return EvaluationExecutionResult(
                evaluation=guarded_eval,
                model_used=f"{self.fallback_model} (fallback)",
                fallback_model_used=True,
                was_compressed=was_compressed,
                prompt_tokens=final_prompt_tokens,
                completion_tokens=final_completion_tokens,
                inference_latency_ms=elapsed_ms,
            )
        except Exception as fallback_exc:
            raise RuntimeError(
                f"Both primary model ('{self.primary_model}') and fallback model "
                f"('{self.fallback_model}') failed evaluation: {fallback_exc}"
            ) from fallback_exc

