from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    IssueCategory,
    ResolutionStatus,
    SentimentTrajectory,
)


class EvidenceSpeaker(str, enum.Enum):
    AGENT = "AGENT"
    CUSTOMER = "CUSTOMER"


class EvidenceIssueType(str, enum.Enum):
    POOR_TONE = "POOR_TONE"
    PREMATURE_CLOSURE = "PREMATURE_CLOSURE"
    UNHELPFUL_RESPONSE = "UNHELPFUL_RESPONSE"
    IGNORED_QUESTION = "IGNORED_QUESTION"


class FlaggedEvidenceQuote(BaseModel):
    """Verbatim quote proving poor tone, misinformation, ignored question, or premature closure."""

    model_config = ConfigDict(extra="forbid")

    speaker: EvidenceSpeaker
    quote: str = Field(..., min_length=1)
    issue_type: EvidenceIssueType


class CoachingPlanItem(BaseModel):
    """Structured coaching step with concrete action and exact suggested phrasing rewrite."""

    model_config = ConfigDict(extra="forbid")

    focus_area: str = Field(..., min_length=3)
    specific_action: str = Field(..., min_length=5)
    suggested_phrasing_example: str = Field(..., min_length=5)


class TicketQAEvaluation(BaseModel):
    """
    Structured Output Schema (`Section 3.2`) bound to `ChatGroq` via
    `.with_structured_output(TicketQAEvaluation, method="json_schema")`.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        ...,
        min_length=50,
        max_length=600,
        description="Concise 2-3 sentence executive summary of the interaction from opening inquiry to closure.",
    )
    core_issue: str = Field(
        ...,
        min_length=10,
        max_length=200,
        description="Root problem the customer sought to resolve, categorized clearly.",
    )
    issue_category: IssueCategory = Field(
        ...,
        description="Standardized classification of the ticket's primary subject matter.",
    )
    resolution_status: ResolutionStatus = Field(
        ...,
        description="Objective classification of the final ticket outcome based on transcript evidence.",
    )
    is_resolved_properly: bool = Field(
        ...,
        description="true ONLY if resolution_status is RESOLVED or ESCALATED_PROPERLY and no premature closure occurred.",
    )
    premature_closure_detected: bool = Field(
        ...,
        description="true if the agent closed the ticket while the customer still had unanswered questions, unverified fixes, or active frustration.",
    )
    premature_closure_reason: Optional[str] = Field(
        default=None,
        description="Required if premature_closure_detected is true; explains the exact evidence of premature closure.",
    )
    agent_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Overall weighted composite QA score calculated according to the system rubric.",
    )
    empathy_rating: int = Field(
        ...,
        ge=1,
        le=10,
        description="Evaluation of warmth, patience, active listening, and emotional validation.",
    )
    clarity_and_accuracy_rating: int = Field(
        ...,
        ge=1,
        le=10,
        description="Evaluation of technical correctness, grammar, formatting, and ease of following instructions.",
    )
    ownership_and_efficiency_rating: int = Field(
        ...,
        ge=1,
        le=10,
        description="Evaluation of proactivity, avoiding unnecessary back-and-forth, and complete resolution.",
    )
    customer_sentiment_trajectory: SentimentTrajectory = Field(
        ...,
        description="How the customer's emotional state shifted between the first and final message.",
    )
    strengths: List[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Specific positive behaviors demonstrated by the agent during the interaction.",
    )
    areas_for_improvement: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Specific gaps, missed opportunities, or policy violations observed.",
    )
    flagged_evidence_quotes: List[FlaggedEvidenceQuote] = Field(
        default_factory=list,
        max_length=4,
        description="Exact verbatim quotes proving poor tone, misinformation, or premature closure.",
    )
    actionable_coaching_plan: List[CoachingPlanItem] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="Structured coaching steps for the agent.",
    )


def get_groq_structured_output_json_schema() -> Dict[str, Any]:
    """Return the exact Section 3.2 JSON Schema definition enforced via Groq Structured Outputs."""
    return {
        "name": "TicketQAEvaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "required": [
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
            ],
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "core_issue": {"type": "string"},
                "issue_category": {
                    "type": "string",
                    "enum": [e.value for e in IssueCategory],
                },
                "resolution_status": {
                    "type": "string",
                    "enum": [e.value for e in ResolutionStatus],
                },
                "is_resolved_properly": {"type": "boolean"},
                "premature_closure_detected": {"type": "boolean"},
                "premature_closure_reason": {"type": ["string", "null"]},
                "agent_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "empathy_rating": {"type": "integer", "minimum": 1, "maximum": 10},
                "clarity_and_accuracy_rating": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                },
                "ownership_and_efficiency_rating": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                },
                "customer_sentiment_trajectory": {
                    "type": "string",
                    "enum": [e.value for e in SentimentTrajectory],
                },
                "strengths": {"type": "array", "items": {"type": "string"}},
                "areas_for_improvement": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "flagged_evidence_quotes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["speaker", "quote", "issue_type"],
                        "additionalProperties": False,
                        "properties": {
                            "speaker": {
                                "type": "string",
                                "enum": [e.value for e in EvidenceSpeaker],
                            },
                            "quote": {"type": "string"},
                            "issue_type": {
                                "type": "string",
                                "enum": [e.value for e in EvidenceIssueType],
                            },
                        },
                    },
                },
                "actionable_coaching_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "focus_area",
                            "specific_action",
                            "suggested_phrasing_example",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "focus_area": {"type": "string"},
                            "specific_action": {"type": "string"},
                            "suggested_phrasing_example": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


def apply_qa_scoring_guardrails(
    evaluation: TicketQAEvaluation,
) -> TicketQAEvaluation:
    """
    Post-Inference Deterministic Guardrail (`Section 3.3`):
    1. Premature Closure Cap: If `premature_closure_detected == True` OR
       `resolution_status == PREMATURELY_CLOSED` OR any quote has `issue_type == PREMATURE_CLOSURE`:
       - `premature_closure_detected = True`
       - `resolution_status = ResolutionStatus.PREMATURELY_CLOSED`
       - `is_resolved_properly = False`
       - `agent_score = min(agent_score, 45)`
       - Ensures `premature_closure_reason` is non-empty.
    2. Poor Tone Cap: If any quote has `issue_type == POOR_TONE`, clamp `agent_score = min(agent_score, 35)`.
    3. Resolution Consistency: `is_resolved_properly` is True ONLY if `resolution_status` in
       `{RESOLVED, ESCALATED_PROPERLY}` and `premature_closure_detected is False`.
    """
    has_premature_quote = any(
        q.issue_type == EvidenceIssueType.PREMATURE_CLOSURE
        for q in evaluation.flagged_evidence_quotes
    )
    has_poor_tone_quote = any(
        q.issue_type == EvidenceIssueType.POOR_TONE
        for q in evaluation.flagged_evidence_quotes
    )

    premature_detected = (
        evaluation.premature_closure_detected
        or evaluation.resolution_status == ResolutionStatus.PREMATURELY_CLOSED
        or has_premature_quote
    )

    clamped_score = evaluation.agent_score
    resolution_status = evaluation.resolution_status
    premature_reason = evaluation.premature_closure_reason

    if premature_detected:
        clamped_score = min(clamped_score, 45)
        resolution_status = ResolutionStatus.PREMATURELY_CLOSED
        if not premature_reason or not premature_reason.strip():
            matching_quotes = [
                q.quote
                for q in evaluation.flagged_evidence_quotes
                if q.issue_type
                in {
                    EvidenceIssueType.PREMATURE_CLOSURE,
                    EvidenceIssueType.IGNORED_QUESTION,
                }
            ]
            if matching_quotes:
                premature_reason = (
                    f"Ticket closed prematurely with unresolved inquiry: '{matching_quotes[0][:140]}'"
                )
            else:
                premature_reason = (
                    "Ticket was closed before confirming that the customer's issue was resolved."
                )

    if has_poor_tone_quote:
        clamped_score = min(clamped_score, 35)

    is_resolved_properly = (
        resolution_status
        in {ResolutionStatus.RESOLVED, ResolutionStatus.ESCALATED_PROPERLY}
        and not premature_detected
    )

    return evaluation.model_copy(
        update={
            "premature_closure_detected": premature_detected,
            "premature_closure_reason": premature_reason
            if premature_detected
            else None,
            "resolution_status": resolution_status,
            "is_resolved_properly": is_resolved_properly,
            "agent_score": clamped_score,
        }
    )

