from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Ops Studio API"
    app_env: str = "development"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_prompt_name: str = "customer-support-answer"
    langfuse_prompt_label: str = "production"
    langfuse_prompt_cache_ttl_seconds: int = Field(default=300, ge=0)
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    database_url: str = "postgresql+asyncpg://aiops:aiops@localhost:5432/aiops"
    redis_url: str = "redis://localhost:6379/0"
    mock_commerce_api_url: str = "http://localhost:8001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
