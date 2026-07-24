from langfuse.openai import OpenAI

from app.config import Settings


def build_openrouter_client(settings: Settings) -> OpenAI | None:
    """Shared OpenRouter client factory used by every AI persona service."""
    if not settings.openrouter_api_key:
        return None
    headers = {
        "HTTP-Referer": settings.openrouter_http_referer,
        "X-OpenRouter-Title": settings.openrouter_app_title,
    }
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers=headers,
        timeout=settings.openrouter_timeout_seconds,
    )
