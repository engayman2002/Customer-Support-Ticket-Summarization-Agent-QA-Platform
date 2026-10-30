from __future__ import annotations

from typing import Any, Optional, Type

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.config import get_settings
from app.LLM_Providers.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude Provider (`LLM_PROVIDER="anthropic"`).
    Reads `ANTHROPIC_API_KEY`, `ANTHROPIC_PRIMARY_MODEL`, `ANTHROPIC_FALLBACK_MODEL`,
    and `ANTHROPIC_COMPRESSION_MODEL` from `backend/.env`.
    """

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        compression_model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        cfg = get_settings()
        resolved_key = (
            api_key if api_key is not None else cfg.ANTHROPIC_API_KEY
        )
        resolved_primary = (
            primary_model
            or cfg.ANTHROPIC_PRIMARY_MODEL
            or "claude-3-5-sonnet-latest"
        )
        resolved_fallback = (
            fallback_model
            or cfg.ANTHROPIC_FALLBACK_MODEL
            or "claude-3-5-haiku-latest"
        )
        resolved_compression = (
            compression_model
            or cfg.ANTHROPIC_COMPRESSION_MODEL
            or resolved_fallback
        )
        super().__init__(
            api_key=resolved_key,
            primary_model=resolved_primary,
            fallback_model=resolved_fallback,
            compression_model=resolved_compression,
            base_url=base_url,
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_chat_client(self, model_name: str, max_tokens: int = 2048) -> Any:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "AnthropicProvider requires `langchain-anthropic`. Install it via `pip install langchain-anthropic`."
            ) from exc

        return ChatAnthropic(
            model=model_name,
            api_key=self.api_key,
            temperature=0.0,
            max_tokens=max_tokens,
            timeout=30.0,
        )

    def get_structured_output_runnable(
        self,
        schema: Type[BaseModel],
        use_fallback: bool = False,
        model_override: Optional[str] = None,
    ) -> Any:
        target_model = model_override or (
            self.fallback_model_name if use_fallback else self.primary_model_name
        )
        llm = self._build_chat_client(target_model, max_tokens=2048)
        return llm.with_structured_output(
            schema,
            include_raw=True,
        )

    async def summarize_chunk(self, system_prompt: str, chunk_text: str) -> str:
        compressor_llm = self._build_chat_client(
            self.compression_model_name, max_tokens=512
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=chunk_text),
        ]
        response = await compressor_llm.ainvoke(messages)
        content = getattr(response, "content", None)
        return content.strip() if isinstance(content, str) else ""

