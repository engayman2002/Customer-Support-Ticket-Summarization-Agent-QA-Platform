from __future__ import annotations

from typing import Any, Optional, Type

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.core.config import get_settings
from app.LLM_Providers.base import BaseLLMProvider


class GroqProvider(BaseLLMProvider):
    """
    Groq LPU Inference Provider (`LLM_PROVIDER="groq"`).
    Reads `GROQ_API_KEY`, `GROQ_PRIMARY_MODEL`, `GROQ_FALLBACK_MODEL`, and
    `GROQ_COMPRESSION_MODEL` from `backend/.env` via `app.core.config.settings`.
    """

    provider_name = "groq"

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
        resolved_key = api_key if api_key is not None else cfg.GROQ_API_KEY
        resolved_primary = (
            primary_model
            or cfg.GROQ_PRIMARY_MODEL
            or "llama-3.3-70b-versatile"
        )
        resolved_fallback = (
            fallback_model
            or cfg.GROQ_FALLBACK_MODEL
            or "llama-3.1-8b-instant"
        )
        resolved_compression = (
            compression_model
            or cfg.GROQ_COMPRESSION_MODEL
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

    def get_structured_output_runnable(
        self,
        schema: Type[BaseModel],
        use_fallback: bool = False,
        model_override: Optional[str] = None,
    ) -> Any:
        target_model = model_override or (
            self.fallback_model_name if use_fallback else self.primary_model_name
        )
        llm = ChatGroq(
            model=target_model,
            api_key=self.api_key,
            temperature=0.0,
            max_tokens=2048,
            timeout=30.0,
            max_retries=1,
        )
        return llm.with_structured_output(
            schema,
            method="json_schema",
            include_raw=True,
        )

    async def summarize_chunk(self, system_prompt: str, chunk_text: str) -> str:
        compressor_llm = ChatGroq(
            model=self.compression_model_name,
            api_key=self.api_key,
            temperature=0.0,
            max_tokens=512,
            timeout=20.0,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=chunk_text),
        ]
        response = await compressor_llm.ainvoke(messages)
        content = getattr(response, "content", None)
        return content.strip() if isinstance(content, str) else ""

