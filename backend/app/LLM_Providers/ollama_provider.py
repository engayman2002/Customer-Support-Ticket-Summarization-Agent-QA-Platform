from __future__ import annotations

from typing import Any, Optional, Type

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.config import get_settings
from app.LLM_Providers.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """
    Local Ollama Provider (`LLM_PROVIDER="ollama"`).
    Reads `OLLAMA_BASE_URL`, `OLLAMA_PRIMARY_MODEL`, `OLLAMA_FALLBACK_MODEL`,
    and `OLLAMA_COMPRESSION_MODEL` from `backend/.env`.
    """

    provider_name = "ollama"

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
        resolved_base_url = (
            base_url
            if base_url is not None
            else (cfg.OLLAMA_BASE_URL or "http://localhost:11434")
        )
        resolved_primary = (
            primary_model or cfg.OLLAMA_PRIMARY_MODEL or "llama3.2"
        )
        resolved_fallback = (
            fallback_model or cfg.OLLAMA_FALLBACK_MODEL or resolved_primary
        )
        resolved_compression = (
            compression_model
            or cfg.OLLAMA_COMPRESSION_MODEL
            or resolved_fallback
        )
        super().__init__(
            api_key=api_key or "",
            primary_model=resolved_primary,
            fallback_model=resolved_fallback,
            compression_model=resolved_compression,
            base_url=resolved_base_url,
        )

    def is_configured(self) -> bool:
        return bool(self.base_url and self.primary_model_name)

    def _build_chat_client(self, model_name: str) -> Any:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise RuntimeError(
                "OllamaProvider requires `langchain-ollama`. Install it via `pip install langchain-ollama`."
            ) from exc

        return ChatOllama(
            model=model_name,
            base_url=self.base_url,
            temperature=0.0,
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
        llm = self._build_chat_client(target_model)
        return llm.with_structured_output(
            schema,
            include_raw=True,
        )

    async def summarize_chunk(self, system_prompt: str, chunk_text: str) -> str:
        compressor_llm = self._build_chat_client(self.compression_model_name)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=chunk_text),
        ]
        response = await compressor_llm.ainvoke(messages)
        content = getattr(response, "content", None)
        return content.strip() if isinstance(content, str) else ""

