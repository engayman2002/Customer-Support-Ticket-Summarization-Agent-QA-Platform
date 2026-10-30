from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Type

import pytest
from pydantic import BaseModel

from app.ai.evaluator import GroqTicketEvaluator, TicketQAEvaluator
from app.core.config import BACKEND_DIR, ROOT_DIR, Settings, get_settings
from app.LLM_Providers import (
    AnthropicProvider,
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    LLMProviderRegistry,
    OllamaProvider,
    OpenAIProvider,
    get_llm_provider,
)
from app.models.enums import (
    IssueCategory,
    ResolutionStatus,
    SentimentTrajectory,
)
from app.schemas.qa_evaluation import (
    CoachingPlanItem,
    TicketQAEvaluation,
)


def test_layered_env_files_exist_and_load_into_settings() -> None:
    """
    Verify that all 3 layers of `.env` and `.env.example` exist (`./.env`, `backend/.env`,
    `frontend/.env`) and that `Settings` loads its configuration from `backend/.env` and `./.env`.
    """
    frontend_dir = ROOT_DIR / "frontend"

    assert (ROOT_DIR / ".env").is_file()
    assert (ROOT_DIR / ".env.example").is_file()
    assert (BACKEND_DIR / ".env").is_file()
    assert (BACKEND_DIR / ".env.example").is_file()
    assert (frontend_dir / ".env").is_file()
    assert (frontend_dir / ".env.example").is_file()

    cfg = Settings()
    assert cfg.DATABASE_URL.startswith("postgresql://")
    assert cfg.ASYNC_DATABASE_URL.startswith("postgresql+asyncpg://")
    assert cfg.REDIS_URL.startswith("redis://")
    assert len(cfg.AUTH_SECRET) >= 32
    assert cfg.LLM_PROVIDER == "groq"
    assert cfg.GROQ_PRIMARY_MODEL == "llama-3.3-70b-versatile"
    assert cfg.GROQ_FALLBACK_MODEL == "llama-3.1-8b-instant"
    assert cfg.OPENAI_PRIMARY_MODEL == "gpt-4o"
    assert cfg.GEMINI_PRIMARY_MODEL == "gemini-2.5-pro"
    assert cfg.ANTHROPIC_PRIMARY_MODEL == "claude-3-5-sonnet-latest"
    assert cfg.OLLAMA_PRIMARY_MODEL == "llama3.2"
    assert cfg.LLM_RPM_LIMIT == 30
    assert cfg.LLM_TPM_LIMIT == 15000
    assert cfg.TRANSCRIPT_MAX_VERBATIM_TOKENS == 10000


def test_llm_provider_registry_resolves_all_builtin_and_custom_providers() -> None:
    """
    Verify `LLMProviderRegistry` resolves `groq`, `openai`, `gemini`, `anthropic`, and `ollama`
    providers cleanly and supports dynamic registration of custom `BaseLLMProvider` subclasses.
    """
    groq_prov = get_llm_provider("groq")
    assert isinstance(groq_prov, GroqProvider)
    assert groq_prov.primary_model_name == "llama-3.3-70b-versatile"
    assert groq_prov.fallback_model_name == "llama-3.1-8b-instant"

    openai_prov = get_llm_provider("openai", api_key="test_openai_placeholder_key")
    assert isinstance(openai_prov, OpenAIProvider)
    assert openai_prov.primary_model_name == "gpt-4o"
    assert openai_prov.fallback_model_name == "gpt-4o-mini"
    assert openai_prov.is_configured() is True

    gemini_prov = get_llm_provider("gemini", api_key="test_gemini_placeholder_key")
    assert isinstance(gemini_prov, GeminiProvider)
    assert gemini_prov.primary_model_name == "gemini-2.5-pro"
    assert gemini_prov.fallback_model_name == "gemini-2.5-flash"
    assert gemini_prov.is_configured() is True

    anthropic_prov = get_llm_provider("anthropic", api_key="test_anthropic_placeholder_key")
    assert isinstance(anthropic_prov, AnthropicProvider)
    assert anthropic_prov.primary_model_name == "claude-3-5-sonnet-latest"
    assert anthropic_prov.fallback_model_name == "claude-3-5-haiku-latest"
    assert anthropic_prov.is_configured() is True

    ollama_prov = get_llm_provider("ollama")
    assert isinstance(ollama_prov, OllamaProvider)
    assert ollama_prov.primary_model_name == "llama3.2"
    assert ollama_prov.is_configured() is True


@pytest.mark.asyncio
async def test_custom_registered_llm_provider_end_to_end_with_evaluator() -> None:
    """
    Register a custom `BaseLLMProvider` implementation in `LLMProviderRegistry` and verify
    that `TicketQAEvaluator` / `GroqTicketEvaluator` executes end-to-end through the provider
    abstraction, including structured output binding and post-inference guardrails.
    """

    class MockEnterpriseLLMProvider(BaseLLMProvider):
        provider_name = "custom_enterprise"

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(
                api_key=kwargs.get("api_key") or "custom_enterprise_token",
                primary_model=kwargs.get("primary_model") or "enterprise-qa-v1",
                fallback_model=kwargs.get("fallback_model") or "enterprise-qa-mini",
                compression_model=kwargs.get("compression_model") or "enterprise-qa-mini",
            )

        def is_configured(self) -> bool:
            return True

        def get_structured_output_runnable(
            self,
            schema: Type[BaseModel],
            use_fallback: bool = False,
            model_override: Optional[str] = None,
        ) -> Any:
            async def _fake_structured_runnable(_messages: Any) -> dict[str, Any]:
                eval_obj = TicketQAEvaluation(
                    summary=(
                        "Customer reported a duplicate charge on their monthly subscription. "
                        "The support agent verified the ledger, refunded the duplicate charge, "
                        "and confirmed the resolution with the customer."
                    ),
                    core_issue="Duplicate monthly subscription billing charge requiring refund.",
                    issue_category=IssueCategory.BILLING,
                    resolution_status=ResolutionStatus.RESOLVED,
                    is_resolved_properly=True,
                    premature_closure_detected=False,
                    premature_closure_reason=None,
                    agent_score=94,
                    empathy_rating=9,
                    clarity_and_accuracy_rating=10,
                    ownership_and_efficiency_rating=9,
                    customer_sentiment_trajectory=SentimentTrajectory.IMPROVED,
                    strengths=[
                        "Immediate ownership of billing audit",
                        "Clear confirmation of refund reference number",
                    ],
                    areas_for_improvement=[],
                    flagged_evidence_quotes=[],
                    actionable_coaching_plan=[
                        CoachingPlanItem(
                            focus_area="Billing Transparency",
                            specific_action="Continue sharing exact invoice and refund IDs in the first resolution turn.",
                            suggested_phrasing_example="I have processed refund #REF-102 for invoice #INV-998.",
                        )
                    ],
                )
                return {
                    "parsed": eval_obj,
                    "raw": None,
                    "parsing_error": None,
                }

            return _fake_structured_runnable

        async def summarize_chunk(self, system_prompt: str, chunk_text: str) -> str:
            return "[COMPRESSED CUSTOM SUMMARY]"

    LLMProviderRegistry.register_provider("custom_enterprise", MockEnterpriseLLMProvider)
    assert "custom_enterprise" in LLMProviderRegistry.list_supported_providers()

    evaluator = TicketQAEvaluator(provider_name="custom_enterprise")
    assert GroqTicketEvaluator is TicketQAEvaluator
    assert evaluator.primary_model == "enterprise-qa-v1"

    result = await evaluator.evaluate_ticket(
        ticket_metadata={
            "ticket_id": "tkt_custom_1",
            "external_ticket_id": "CUST-001",
            "subject": "Duplicate billing charge",
            "priority": "HIGH",
        },
        raw_transcript=[
            {
                "message_id": "m1",
                "sender_role": "CUSTOMER",
                "sender_name": "Customer",
                "content": "I was charged twice for my subscription this month.",
                "timestamp": "2026-10-30T00:00:00Z",
            },
            {
                "message_id": "m2",
                "sender_role": "AGENT",
                "sender_name": "Sarah Jenkins",
                "content": "I have refunded the duplicate charge and verified your account.",
                "timestamp": "2026-10-30T00:05:00Z",
            },
        ],
    )

    assert result.model_used == "enterprise-qa-v1"
    assert result.fallback_model_used is False
    assert result.evaluation.agent_score == 94
    assert result.evaluation.is_resolved_properly is True

