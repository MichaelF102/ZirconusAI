"""Application configuration loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV), str(_BACKEND_ENV)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    tavily_api_key: str = ""

    database_url: str = "sqlite:///./research.db"

    max_subquestions: int = Field(default=4, ge=1, le=8)
    max_sources_per_subquestion: int = Field(default=5, ge=1, le=10)
    max_revision_cycles: int = Field(default=2, ge=0, le=5)
    request_timeout_seconds: float = Field(default=20, gt=0, le=120)
    llm_timeout_seconds: float = Field(default=90, gt=0, le=600)
    max_research_seconds: float = Field(default=900, gt=0)
    max_concurrent_research: int = Field(default=2, ge=1, le=10)
    max_concurrent_searches: int = Field(default=3, ge=1, le=10)
    max_concurrent_fetches: int = Field(default=5, ge=1, le=20)
    max_source_chars: int = Field(default=12000, ge=500)
    max_fetch_bytes: int = Field(default=3_000_000, ge=10_000)
    llm_max_retries: int = Field(default=3, ge=0, le=6)
    create_rate_limit_per_minute: int = Field(default=10, ge=1)

    frontend_origin: str = "http://localhost:3000"
    log_level: str = "INFO"

    @field_validator("frontend_origin")
    @classmethod
    def _strip_origin(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    def missing_credentials(self) -> list[str]:
        missing = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.tavily_api_key:
            missing.append("TAVILY_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
