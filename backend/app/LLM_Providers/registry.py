from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from app.core.config import get_settings
from app.LLM_Providers.anthropic_provider import AnthropicProvider
from app.LLM_Providers.base import BaseLLMProvider
from app.LLM_Providers.gemini_provider import GeminiProvider
from app.LLM_Providers.groq_provider import GroqProvider
from app.LLM_Providers.ollama_provider import OllamaProvider
from app.LLM_Providers.openai_provider import OpenAIProvider


class LLMProviderRegistry:
    """
    Central Registry & Factory for Pluggable Multi-LLM Providers (`backend/app/LLM_Providers/`).

    Allows switching the active LLM provider globally via `LLM_PROVIDER` in `backend/.env`
    or registering custom `BaseLLMProvider` implementations at runtime.
    """

    _providers: Dict[str, Type[BaseLLMProvider]] = {
        "groq": GroqProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "google": GeminiProvider,
        "anthropic": AnthropicProvider,
        "claude": AnthropicProvider,
        "ollama": OllamaProvider,
    }

    @classmethod
    def register_provider(
        cls,
        provider_name: str,
        provider_cls: Type[BaseLLMProvider],
    ) -> None:
        """Register a new or custom `BaseLLMProvider` class under `provider_name`."""
        normalized = provider_name.strip().lower()
        if not normalized:
            raise ValueError("provider_name must be a non-empty string.")
        if not issubclass(provider_cls, BaseLLMProvider):
            raise TypeError(
                f"{provider_cls!r} must subclass BaseLLMProvider."
            )
        cls._providers[normalized] = provider_cls

    @classmethod
    def list_supported_providers(cls) -> List[str]:
        """Return sorted list of registered LLM provider keys."""
        return sorted(cls._providers.keys())

    @classmethod
    def get_provider(
        cls,
        provider_name: Optional[str] = None,
        **kwargs: Any,
    ) -> BaseLLMProvider:
        """
        Instantiate and return the requested `BaseLLMProvider` (defaults to `settings.LLM_PROVIDER`
        from `backend/.env`).
        """
        cfg = get_settings()
        target_name = (provider_name or cfg.LLM_PROVIDER or "groq").strip().lower()
        provider_cls = cls._providers.get(target_name)
        if provider_cls is None:
            supported = ", ".join(cls.list_supported_providers())
            raise ValueError(
                f"Unsupported LLM_PROVIDER '{target_name}'. Supported providers: {supported}"
            )
        return provider_cls(**kwargs)


def get_llm_provider(
    provider_name: Optional[str] = None,
    **kwargs: Any,
) -> BaseLLMProvider:
    """Convenience factory function delegating to `LLMProviderRegistry.get_provider`."""
    return LLMProviderRegistry.get_provider(provider_name=provider_name, **kwargs)

