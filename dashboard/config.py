"""Dashboard configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    dashboard_port: int = Field(8100, alias="DASHBOARD_PORT")
    database_dsn: str = Field("dbname=recordings", alias="DATABASE_DSN")
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-haiku-4-5", alias="ANTHROPIC_MODEL")
    ollama_base_url: str = Field("http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("qwen3.6:latest", alias="OLLAMA_MODEL")
    ai_provider: str = Field("auto", alias="AI_PROVIDER")
    voice_capture_dashboard_url: str = Field(
        "http://localhost:8100", alias="VOICE_CAPTURE_DASHBOARD_URL"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
