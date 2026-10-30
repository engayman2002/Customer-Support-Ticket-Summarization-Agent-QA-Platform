from __future__ import annotations

from typing import Any, Optional, Type

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.config import get_settings
from app.LLM_Providers.base import BaseLLMProvider


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini Provider (`LLM_PROVIDER="gemini"`).
    Reads `GEMINI_API_KEY`, `GEMINI_PRIMARY_MODEL`, `GEMINI_FALLBACK_MODEL`,
    and `GEMINI_COMPRESSION_MODEL` from `backend/.env`.
    """

    provider_name = "gemini"

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
        resolved_key = api_key if api_key is not None else cfg.GEMINI_API_KEY
        resolved_primary = (
            primary_model or cfg.GEMINI_PRIMARY_MODEL or "gemini-2.5-pro"
        )
        resolved_fallback = (
            fallback_model or cfg.GEMINI_FALLBACK_MODEL or "gemini-2.5-flash"
        )
        resolved_compression = (
            compression_model
            or cfg.GEMINI_COMPRESSION_MODEL
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
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise RuntimeError(
                "GeminiProvider requires `langchain-google-genai`. Install it via `pip install langchain-google-genai`."
            ) from exc

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=self.api_key,
            temperature=0.0,
            max_output_tokens=max_tokens,
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

