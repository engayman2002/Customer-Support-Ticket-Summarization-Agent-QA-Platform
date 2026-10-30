from __future__ import annotations

import abc
from typing import Any, Optional, Type

from pydantic import BaseModel


class BaseLLMProvider(abc.ABC):
    """
    Abstract Strategy Interface for Pluggable Multi-LLM Providers (`backend/app/LLM_Providers/`).

    Every concrete provider (`GroqProvider`, `OpenAIProvider`, `GeminiProvider`,
    `AnthropicProvider`, `OllamaProvider`, or custom user-defined providers) implements
    this contract so the QA Evaluation Pipeline (`TicketQAEvaluator`) remains 100%
    decoupled from any specific LLM vendor SDK.
    """

    provider_name: str = "base"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        compression_model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._primary_model = (primary_model or "").strip()
        self._fallback_model = (fallback_model or "").strip()
        self._compression_model = (compression_model or "").strip()
        self._base_url = (base_url or "").strip()

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def primary_model_name(self) -> str:
        return self._primary_model

    @property
    def fallback_model_name(self) -> str:
        return self._fallback_model or self._primary_model

    @property
    def compression_model_name(self) -> str:
        return self._compression_model or self.fallback_model_name

    @property
    def base_url(self) -> str:
        return self._base_url

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """
        Return `True` if this provider has the credentials/endpoint required to make
        live LLM inference requests, or `False` if the evaluator should use its
        offline deterministic rubric fallback.
        """

    @abc.abstractmethod
    def get_structured_output_runnable(
        self,
        schema: Type[BaseModel],
        use_fallback: bool = False,
        model_override: Optional[str] = None,
    ) -> Any:
        """
        Return a LangChain Runnable bound with `.with_structured_output(schema, include_raw=True)`
        for either the primary model (`use_fallback=False`) or fallback model (`use_fallback=True`).
        """

    def get_structured_Allocation_runnable(
        self,
        schema: Type[BaseModel],
        use_fallback: bool = False,
        model_override: Optional[str] = None,
    ) -> Any:
        """Alias for `get_structured_output_runnable` for interface compatibility."""
        return self.get_structured_output_runnable(
            schema=schema,
            use_fallback=use_fallback,
            model_override=model_override,
        )

    @abc.abstractmethod
    async def summarize_chunk(self, system_prompt: str, chunk_text: str) -> str:
        """
        Summarize a middle transcript segment using the provider's fast compression model.
        """

