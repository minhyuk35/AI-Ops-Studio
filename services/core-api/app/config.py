import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def running_on_vercel() -> bool:
    """True inside a Vercel Function (build or runtime) -- see
    docs/vercel-deployment.md. Used to skip the asyncio background-loop
    schedulers (which never wake back up between serverless invocations)
    in favor of Vercel Cron Jobs hitting app/api/routes/cron.py instead.

    VERCEL is only set when the project has "Automatically expose System
    Environment Variables" turned on. AWS_LAMBDA_FUNCTION_NAME comes from
    the underlying Lambda runtime Vercel's Python functions run on and
    isn't gated by that toggle, so check it too rather than silently
    falling through to local-dev behavior on a real deployment.
    """
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def _default_mock_commerce_api_url() -> str:
    """On Vercel, core-api and mock-commerce-api are two services in the
    same deployment (see vercel.json) -- reach the commerce service through
    this deployment's own domain under /api/commerce rather than hardcoding
    a URL that wouldn't exist for preview deployments. Explicitly setting
    MOCK_COMMERCE_API_URL still overrides this.

    VERCEL_URL is only populated when the project has "Automatically expose
    System Environment Variables" turned on -- if that toggle is off,
    VERCEL_URL (and VERCEL itself) are silently missing even in production,
    and every AI endpoint that talks to the commerce API fails fast against
    a localhost:8001 that doesn't exist inside the function.
    AWS_LAMBDA_FUNCTION_NAME is injected by the underlying Lambda runtime
    Vercel's Python functions run on, independent of that toggle, so it's a
    reliable "are we actually deployed" signal even when VERCEL_URL isn't.
    CORS_ORIGINS already has to carry the real production domain for the
    browser to work at all, so reuse its first https origin in that case.
    """
    vercel_url = os.getenv("VERCEL_URL")
    if running_on_vercel() and vercel_url:
        return f"https://{vercel_url}/api/commerce"
    if running_on_vercel():
        for origin in os.getenv("CORS_ORIGINS", "").split(","):
            origin = origin.strip()
            if origin.startswith("https://"):
                return f"{origin}/api/commerce"
    return "http://localhost:8001"


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

    # Unused by any current store (InquiryStore/OpsStore read DATABASE_URL
    # directly via os.getenv, see app/services/db_compat.py) -- kept only so
    # this field doesn't silently diverge from .env.example's default.
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    mock_commerce_api_url: str = Field(default_factory=_default_mock_commerce_api_url)
    mock_commerce_timeout_seconds: float = Field(default=10, ge=1, le=60)

    discord_webhook_url: str = ""
    admin_discord_webhook_url: str = ""
    discord_timeout_seconds: float = Field(default=10, ge=1, le=30)

    # Verifies Vercel Cron requests to app/api/routes/cron.py (Authorization:
    # Bearer <this>). Empty means those endpoints refuse everything -- see
    # docs/vercel-deployment.md.
    cron_secret: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
