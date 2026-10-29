from __future__ import annotations

import uuid
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.ai import (
    QA_AUDITOR_SYSTEM_PROMPT,
    acquire_groq_rate_limit,
    build_evaluation_prompt_messages,
    count_tokens,
    prepare_transcript_for_evaluation,
    reset_groq_rate_limit,
)
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
    get_groq_structured_output_json_schema,
)


def _make_valid_evaluation_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "summary": (
            "Customer reported duplicate card charge on invoice INV-8841. "
            "Agent verified Stripe ledger, refunded the duplicate capture, "
            "and confirmed settlement timeline with the customer."
        ),
        "core_issue": "Duplicate credit card capture on monthly subscription renewal.",
        "issue_category": IssueCategory.BILLING,
        "resolution_status": ResolutionStatus.RESOLVED,
        "is_resolved_properly": True,
        "premature_closure_detected": False,
        "premature_closure_reason": None,
        "agent_score": 94,
        "empathy_rating": 9,
        "clarity_and_accuracy_rating": 10,
        "ownership_and_efficiency_rating": 9,
        "customer_sentiment_trajectory": SentimentTrajectory.IMPROVED,
        "strengths": [
            "Verified gateway transaction ledger on the first reply.",
            "Provided refund reference ID and clear settlement timeline.",
        ],
        "areas_for_improvement": [
            "Could share self-service receipt link in the closing note."
        ],
        "flagged_evidence_quotes": [],
        "actionable_coaching_plan": [
            {
                "focus_area": "Proactive Billing Self-Service",
                "specific_action": "Include a direct link to the billing receipt portal when confirming a refund.",
                "suggested_phrasing_example": (
                    "I have processed refund ref_991—you can download the updated receipt anytime from Settings > Billing."
                ),
            }
        ],
    }
    base.update(overrides)
    return base


def test_ticket_qa_evaluation_schema_and_section_3_2_json_schema_parity() -> None:
    """
    Step 6.1: Validate `TicketQAEvaluation` against valid and invalid payloads
    and verify `get_groq_structured_output_json_schema()` matches Section 3.2.
    """
    valid_eval = TicketQAEvaluation.model_validate(_make_valid_evaluation_dict())
    assert valid_eval.agent_score == 94
    assert valid_eval.issue_category == IssueCategory.BILLING
    assert valid_eval.resolution_status == ResolutionStatus.RESOLVED
    assert valid_eval.is_resolved_properly is True

    # Reject agent_score > 100
    with pytest.raises(ValidationError):
        TicketQAEvaluation.model_validate(
            _make_valid_evaluation_dict(agent_score=105)
        )

    # Reject empathy_rating > 10 or < 1
    with pytest.raises(ValidationError):
        TicketQAEvaluation.model_validate(
            _make_valid_evaluation_dict(empathy_rating=11)
        )

    # Reject summary shorter than 50 chars
    with pytest.raises(ValidationError):
        TicketQAEvaluation.model_validate(
            _make_valid_evaluation_dict(summary="Too short summary.")
        )

    # Reject empty strengths or actionable_coaching_plan (`min_length=1`)
    with pytest.raises(ValidationError):
        TicketQAEvaluation.model_validate(
            _make_valid_evaluation_dict(strengths=[])
        )
    with pytest.raises(ValidationError):
        TicketQAEvaluation.model_validate(
            _make_valid_evaluation_dict(actionable_coaching_plan=[])
        )

    # Reject unknown extra properties (`extra="forbid"`)
    with pytest.raises(ValidationError):
        TicketQAEvaluation.model_validate(
            _make_valid_evaluation_dict(unexpected_field="not_allowed")
        )

    # Verify Groq Structured Outputs JSON Schema contract (Section 3.2)
    json_schema_block = get_groq_structured_output_json_schema()
    assert json_schema_block["name"] == "TicketQAEvaluation"
    assert json_schema_block["strict"] is True

    schema = json_schema_block["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False

    expected_required = {
        "summary",
        "core_issue",
        "issue_category",
        "resolution_status",
        "is_resolved_properly",
        "premature_closure_detected",
        "premature_closure_reason",
        "agent_score",
        "empathy_rating",
        "clarity_and_accuracy_rating",
        "ownership_and_efficiency_rating",
        "customer_sentiment_trajectory",
        "strengths",
        "areas_for_improvement",
        "flagged_evidence_quotes",
        "actionable_coaching_plan",
    }
    assert set(schema["required"]) == expected_required
    assert schema["properties"]["agent_score"]["minimum"] == 0
    assert schema["properties"]["agent_score"]["maximum"] == 100
    assert schema["properties"]["empathy_rating"]["minimum"] == 1
    assert schema["properties"]["empathy_rating"]["maximum"] == 10


def test_post_inference_guardrails_clamp_contradictory_scores() -> None:
    """
    Step 6.2: Verify `apply_qa_scoring_guardrails()` deterministically enforces:
    1. Premature closure clamp (`agent_score` 88 -> 45, `is_resolved_properly=False`,
       `resolution_status=PREMATURELY_CLOSED`, non-empty `premature_closure_reason`).
    2. Hostile / poor tone clamp (`POOR_TONE` quote -> `agent_score <= 35`).
    3. `is_resolved_properly` consistency invariant when status is `UNRESOLVED`.
    """
    # 1. Premature Closure Clamp (Section 3.3)
    contradictory_premature = TicketQAEvaluation.model_validate(
        _make_valid_evaluation_dict(
            agent_score=88,
            premature_closure_detected=True,
            is_resolved_properly=True,
            resolution_status=ResolutionStatus.RESOLVED,
            premature_closure_reason=None,
        )
    )
    clamped_premature = apply_qa_scoring_guardrails(contradictory_premature)
    assert clamped_premature.agent_score == 45
    assert clamped_premature.is_resolved_properly is False
    assert (
        clamped_premature.resolution_status
        == ResolutionStatus.PREMATURELY_CLOSED
    )
    assert clamped_premature.premature_closure_reason is not None
    assert len(clamped_premature.premature_closure_reason) > 10

    # 2. Hostile / Poor Tone Clamp (`POOR_TONE` -> `agent_score <= 35`)
    contradictory_poor_tone = TicketQAEvaluation.model_validate(
        _make_valid_evaluation_dict(
            agent_score=78,
            premature_closure_detected=False,
            flagged_evidence_quotes=[
                FlaggedEvidenceQuote(
                    speaker=EvidenceSpeaker.AGENT,
                    quote="If you read the manual you would not be asking this.",
                    issue_type=EvidenceIssueType.POOR_TONE,
                ).model_dump()
            ],
        )
    )
    clamped_tone = apply_qa_scoring_guardrails(contradictory_poor_tone)
    assert clamped_tone.agent_score == 35

    # Combined Premature Closure + Poor Tone -> clamped to min(45, 35) == 35
    combined = TicketQAEvaluation.model_validate(
        _make_valid_evaluation_dict(
            agent_score=92,
            premature_closure_detected=True,
            is_resolved_properly=True,
            resolution_status=ResolutionStatus.RESOLVED,
            flagged_evidence_quotes=[
                FlaggedEvidenceQuote(
                    speaker=EvidenceSpeaker.AGENT,
                    quote="Stop reopening this ticket.",
                    issue_type=EvidenceIssueType.POOR_TONE,
                ).model_dump()
            ],
        )
    )
    clamped_combined = apply_qa_scoring_guardrails(combined)
    assert clamped_combined.agent_score == 35
    assert clamped_combined.is_resolved_properly is False
    assert (
        clamped_combined.resolution_status
        == ResolutionStatus.PREMATURELY_CLOSED
    )

    # 3. Consistency Invariant (`resolution_status == UNRESOLVED` -> `is_resolved_properly = False`)
    unresolved_status_eval = TicketQAEvaluation.model_validate(
        _make_valid_evaluation_dict(
            agent_score=58,
            is_resolved_properly=True,
            resolution_status=ResolutionStatus.UNRESOLVED,
            premature_closure_detected=False,
        )
    )
    clamped_unresolved = apply_qa_scoring_guardrails(unresolved_status_eval)
    assert clamped_unresolved.is_resolved_properly is False


def test_system_prompt_rubric_and_evaluation_message_builder() -> None:
    """
    Step 6.3: Verify `QA_AUDITOR_SYSTEM_PROMPT` contains all 4 weighted scoring pillars,
    premature closure rules, and mandatory penalty caps (45 and 35), and verify
    `build_evaluation_prompt_messages()` returns `[SystemMessage, HumanMessage]`.
    """
    for section_phrase in (
        "PREMATURE CLOSURE DETECTION RULES",
        "Pillar A: Issue Resolution & Completeness (40 Points Max)",
        "Pillar B: Communication Clarity & Accuracy (25 Points Max)",
        "Pillar C: Empathy, Tone & Professionalism (20 Points Max)",
        "Pillar D: Process Efficiency & Ownership (15 Points Max)",
        "MANDATORY PENALTY CAPS",
        "COACHING PLAN REQUIREMENTS",
    ):
        assert section_phrase in QA_AUDITOR_SYSTEM_PROMPT

    messages = build_evaluation_prompt_messages(
        ticket_metadata={
            "external_ticket_id": "ZD-99412",
            "subject": "SSO Login Failure After IdP Certificate Rotation",
            "priority": "URGENT",
            "channel": "EMAIL",
            "created_at": "2026-10-28T09:15:00Z",
            "closed_at": "2026-10-28T11:42:00Z",
        },
        formatted_transcript="[Turn #1 | 2026-10-28 09:15 UTC | CUSTOMER]: SAML assertion failed.",
    )
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == QA_AUDITOR_SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert "ZD-99412" in messages[1].content
    assert "SSO Login Failure After IdP Certificate Rotation" in messages[1].content
    assert "SAML assertion failed." in messages[1].content


@pytest.mark.asyncio
async def test_head_body_tail_context_window_compressor() -> None:
    """
    Step 6.4: Verify `prepare_transcript_for_evaluation()`:
    - Short transcripts (`<= 10,000` tokens) return `(formatted_transcript, False)` verbatim.
    - Long transcripts (`> 10,000` tokens) return `(compressed_transcript, True)`, preserving
      the First 4 Head turns verbatim at the top, compressing Middle turns (`5` to `N-8`) in
      4,000-token windows, and preserving the Final 8 Tail turns verbatim at the bottom.
    """
    # 1. Short Transcript (<= 10,000 tokens)
    short_turns = [
        {
            "sender_role": "CUSTOMER" if i % 2 == 0 else "AGENT",
            "timestamp": f"2026-10-29T10:{i:02d}:00Z",
            "content": f"Short turn {i} message body.",
        }
        for i in range(6)
    ]
    short_text, short_was_compressed = await prepare_transcript_for_evaluation(
        short_turns
    )
    assert short_was_compressed is False
    for i in range(6):
        assert f"Short turn {i} message body." in short_text

    # 2. Long Transcript (> 10,000 tokens across 30 turns)
    repeated_filler = (
        "Diagnostic log trace for enterprise SAML gateway cluster node alpha-07 "
        "verifying TLS handshake cipher suite negotiation and X509 certificate chain. "
    ) * 20  # ~450 tokens per turn -> ~13,500 tokens across 30 turns
    long_turns = [
        {
            "sender_role": "CUSTOMER" if i % 2 == 0 else "AGENT",
            "timestamp": f"2026-10-29T12:{i % 60:02d}:00Z",
            "content": f"UNIQUE_MARKER_TURN_{i + 1:02d}_START :: {repeated_filler} :: UNIQUE_MARKER_TURN_{i + 1:02d}_END",
        }
        for i in range(30)
    ]

    summarizer_chunks: list[str] = []

    async def mock_middle_summarizer(chunk_text: str) -> str:
        summarizer_chunks.append(chunk_text)
        return (
            f"Summarized middle window ({count_tokens(chunk_text)} tokens): "
            "Agent and customer exchanged SAML gateway diagnostic logs."
        )

    long_text, long_was_compressed = await prepare_transcript_for_evaluation(
        long_turns,
        max_tokens=10000,
        summarizer_fn=mock_middle_summarizer,
    )

    assert long_was_compressed is True
    assert len(summarizer_chunks) >= 2
    assert count_tokens(long_text) < 10000

    # Verify First 4 Head turns (Turns #1..#4) are preserved verbatim at the top
    for head_turn in range(1, 5):
        assert f"UNIQUE_MARKER_TURN_{head_turn:02d}_START" in long_text
        assert f"UNIQUE_MARKER_TURN_{head_turn:02d}_END" in long_text

    # Verify Middle turns (Turns #5..#22) were compressed and replaced by the summary block
    for mid_turn in range(5, 23):
        assert f"UNIQUE_MARKER_TURN_{mid_turn:02d}_START" not in long_text
    assert "--- [MIDDLE SEGMENT COMPRESSED: Turns #5 to #22] ---" in long_text
    assert "[Compressed Middle Window #1]: Summarized middle window" in long_text

    # Verify Final 8 Tail turns (Turns #23..#30) are preserved verbatim at the bottom
    for tail_turn in range(23, 31):
        assert f"UNIQUE_MARKER_TURN_{tail_turn:02d}_START" in long_text
        assert f"UNIQUE_MARKER_TURN_{tail_turn:02d}_END" in long_text

    # Verify strict Head -> Middle -> Tail ordering
    pos_head = long_text.index("UNIQUE_MARKER_TURN_01_START")
    pos_mid = long_text.index("--- [MIDDLE SEGMENT COMPRESSED: Turns #5 to #22] ---")
    pos_tail = long_text.index("UNIQUE_MARKER_TURN_30_START")
    assert pos_head < pos_mid < pos_tail


@pytest.mark.asyncio
async def test_redis_lua_dual_bucket_rate_limiter_rpm_and_tpm() -> None:
    """
    Step 6.5: Against live Redis (`localhost:6379`), verify `acquire_groq_rate_limit()`:
    - Allows requests within RPM and TPM limits.
    - Rejects requests exceeding RPM (`allowed == False`, `retry_after_seconds > 0`).
    - Rejects requests exceeding TPM (`allowed == False`, `retry_after_seconds > 0`)
      while still allowing a smaller token request that fits inside the remaining TPM budget.
    """
    rpm_scope = f"test_rpm_{uuid.uuid4().hex[:8]}"
    tpm_scope = f"test_tpm_{uuid.uuid4().hex[:8]}"

    try:
        # 1. Test RPM saturation (rpm_limit=3, tpm_limit=15000)
        for _ in range(3):
            allowed, retry_after = await acquire_groq_rate_limit(
                estimated_tokens=500,
                rpm_limit=3,
                tpm_limit=15000,
                scope=rpm_scope,
            )
            assert allowed is True
            assert retry_after == 0.0

        # 4th request exceeds RPM (3/3 used) -> rejected with retry_after > 0
        allowed_4th, retry_after_4th = await acquire_groq_rate_limit(
            estimated_tokens=500,
            rpm_limit=3,
            tpm_limit=15000,
            scope=rpm_scope,
        )
        assert allowed_4th is False
        assert retry_after_4th > 0.0

        # 2. Test TPM saturation (rpm_limit=30, tpm_limit=1000)
        allowed_tpm_1, retry_tpm_1 = await acquire_groq_rate_limit(
            estimated_tokens=600,
            rpm_limit=30,
            tpm_limit=1000,
            scope=tpm_scope,
        )
        assert allowed_tpm_1 is True
        assert retry_tpm_1 == 0.0

        # 2nd request of 600 tokens (600 + 600 = 1200 > 1000 TPM) -> rejected
        allowed_tpm_2, retry_tpm_2 = await acquire_groq_rate_limit(
            estimated_tokens=600,
            rpm_limit=30,
            tpm_limit=1000,
            scope=tpm_scope,
        )
        assert allowed_tpm_2 is False
        assert retry_tpm_2 > 0.0

        # Smaller request of 350 tokens (600 + 350 = 950 <= 1000 TPM) -> allowed!
        allowed_smaller, retry_smaller = await acquire_groq_rate_limit(
            estimated_tokens=350,
            rpm_limit=30,
            tpm_limit=1000,
            scope=tpm_scope,
        )
        assert allowed_smaller is True
        assert retry_smaller == 0.0
    finally:
        await reset_groq_rate_limit(scope=rpm_scope)
        await reset_groq_rate_limit(scope=tpm_scope)
