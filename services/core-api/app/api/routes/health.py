from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "core-api"}


@router.get("/debug-notifier")
async def debug_notifier() -> dict[str, object]:
    """Temporary: diagnosing why the support-escalation Discord alert isn't
    arriving. Remove once confirmed fixed."""
    settings = get_settings()
    url = settings.discord_webhook_url
    return {
        "discord_webhook_url_set": bool(url),
        "discord_webhook_url_len": len(url),
        "discord_webhook_url_suffix": url[-12:] if url else "",
    }
