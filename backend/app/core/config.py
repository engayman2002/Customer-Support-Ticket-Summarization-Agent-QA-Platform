from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """
    Centralized Backend Configuration loaded from `backend/.env` (with fallback to root `./.env`).
    All infrastructure URLs, cryptographic secrets, rate-limit budgets, and multi-LLM
    provider settings are driven by `.env` files rather than hardcoded literals.
    """

    PROJECT_NAME: str = "Customer Support Ticket Summarization & Agent QA Platform"
    API_V1_STR: str = "/api/v1"

    # --- Database & Redis Connections (Loaded from `backend/.env` / `./.env`) ---
    DATABASE_URL: str = ""
    ASYNC_DATABASE_URL: str = ""
    REDIS_URL: str = ""

    # --- Security, JWT & AES-256-GCM Credential Encryption ---
    AUTH_SECRET: str = ""
    ENCRYPTION_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    CORS_ORIGINS: str = ""

    # --- Pluggable Multi-LLM Provider Selection (`backend/app/LLM_Providers/`) ---
    # Supported built-in providers: "groq" | "openai" | "gemini" | "anthropic" | "ollama"
    LLM_PROVIDER: str = "groq"

    # 1. Groq LPU Provider Settings
    GROQ_API_KEY: str = ""
    GROQ_PRIMARY_MODEL: str = ""
    GROQ_FALLBACK_MODEL: str = ""
    GROQ_COMPRESSION_MODEL: str = ""

    # 2. OpenAI / OpenAI-Compatible Provider Settings
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_PRIMARY_MODEL: str = ""
    OPENAI_FALLBACK_MODEL: str = ""
    OPENAI_COMPRESSION_MODEL: str = ""

    # 3. Google Gemini Provider Settings
    GEMINI_API_KEY: str = ""
    GEMINI_PRIMARY_MODEL: str = ""
    GEMINI_FALLBACK_MODEL: str = ""
    GEMINI_COMPRESSION_MODEL: str = ""

    # 4. Anthropic Claude Provider Settings
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_PRIMARY_MODEL: str = ""
    ANTHROPIC_FALLBACK_MODEL: str = ""
    ANTHROPIC_COMPRESSION_MODEL: str = ""

    # 5. Local Ollama Provider Settings
    OLLAMA_BASE_URL: str = ""
    OLLAMA_PRIMARY_MODEL: str = ""
    OLLAMA_FALLBACK_MODEL: str = ""
    OLLAMA_COMPRESSION_MODEL: str = ""

    # --- Distributed Rate Limiter & Context Window Budgets ---
    LLM_RPM_LIMIT: int = 30
    LLM_TPM_LIMIT: int = 15000
    GROQ_RPM_LIMIT: int = 30
    GROQ_TPM_LIMIT: int = 15000
    TRANSCRIPT_MAX_VERBATIM_TOKENS: int = 10000

    model_config = SettingsConfigDict(
        env_file=(
            ".env",
            str(ROOT_DIR / ".env"),
            str(BACKEND_DIR / ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
