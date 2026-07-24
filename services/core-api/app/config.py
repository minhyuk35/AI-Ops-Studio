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

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "~google/gemini-flash-latest"
    openrouter_http_referer: str = "http://localhost:5173"
    openrouter_app_title: str = "AI Ops Studio"
    openrouter_timeout_seconds: float = Field(default=30, ge=1, le=120)

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_prompt_label: str = "production"
    langfuse_prompt_cache_ttl_seconds: int = Field(default=300, ge=0)
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    langfuse_support_prompt_name: str = "customer-support-answer"
    langfuse_triage_prompt_name: str = "support-triage"
    langfuse_commerce_insight_prompt_name: str = "commerce-insight"
    langfuse_monthly_report_prompt_name: str = "commerce-monthly-report"
    langfuse_daily_seller_report_prompt_name: str = "daily-seller-report"
    langfuse_platform_traffic_prompt_name: str = "platform-daily-traffic"
    langfuse_seller_market_share_prompt_name: str = "seller-market-share-report"

    daily_report_hour_utc: int = Field(default=0, ge=0, le=23)
    platform_traffic_report_hour_utc: int = Field(default=1, ge=0, le=23)
    monthly_report_day_utc: int = Field(default=1, ge=1, le=28)

    database_url: str = "postgresql+asyncpg://aiops:aiops@localhost:5432/aiops"
    redis_url: str = "redis://localhost:6379/0"
    mock_commerce_api_url: str = "http://localhost:8001"
    mock_commerce_timeout_seconds: float = Field(default=10, ge=1, le=60)

    discord_webhook_url: str = ""
    admin_discord_webhook_url: str = ""
    discord_timeout_seconds: float = Field(default=10, ge=1, le=30)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
