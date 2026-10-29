from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    PROJECT_NAME: str = "Customer Support Ticket Summarization & Agent QA Platform"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = (
        "postgresql://qa_admin:qa_secret_password@localhost:5432/qa_platform_db?schema=public"
    )
    ASYNC_DATABASE_URL: str = (
        "postgresql+asyncpg://qa_admin:qa_secret_password@localhost:5432/qa_platform_db"
    )
    REDIS_URL: str = "redis://localhost:6379/0"

    AUTH_SECRET: str = "super-secret-shared-hs256-signing-key-minimum-32-bytes-long-2026"
    ENCRYPTION_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    CORS_ORIGINS: str = "http://localhost:3000"

    # --- Phase 3: Groq LPU Inference & Context Window Settings ---
    GROQ_API_KEY: str = ""
    GROQ_PRIMARY_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_FALLBACK_MODEL: str = "llama-3.1-8b-instant"
    GROQ_COMPRESSION_MODEL: str = "llama-3.1-8b-instant"
    GROQ_RPM_LIMIT: int = 30
    GROQ_TPM_LIMIT: int = 15000
    TRANSCRIPT_MAX_VERBATIM_TOKENS: int = 10000

    model_config = SettingsConfigDict(
        env_file=(
            str(BACKEND_DIR / ".env"),
            str(ROOT_DIR / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
