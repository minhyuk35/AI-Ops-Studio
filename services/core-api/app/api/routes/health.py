import os

import httpx
from fastapi import APIRouter

from app.config import get_settings, running_on_vercel

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "core-api"}


@router.get("/debug-commerce-url")
async def debug_commerce_url() -> dict[str, object]:
    """Temporary: diagnosing the seller-daily-report 500 in prod. Remove
    once the "데이터를 불러오지 못했습니다" bug is confirmed fixed."""
    settings = get_settings()
    raw_env_value = os.getenv("MOCK_COMMERCE_API_URL")
    result: dict[str, object] = {
        "resolved_mock_commerce_api_url": settings.mock_commerce_api_url,
        "raw_env_MOCK_COMMERCE_API_URL": raw_env_value,
        "running_on_vercel": running_on_vercel(),
        "has_VERCEL": bool(os.getenv("VERCEL")),
        "has_VERCEL_URL": bool(os.getenv("VERCEL_URL")),
        "VERCEL_URL_value": os.getenv("VERCEL_URL"),
        "has_AWS_LAMBDA_FUNCTION_NAME": bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME")),
        "cors_origins": settings.cors_origins,
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.mock_commerce_api_url.rstrip("/"), timeout=5
        ) as client:
            response = await client.get("/health")
            result["probe_status"] = response.status_code
            result["probe_body"] = response.text[:200]
    except Exception as exc:  # noqa: BLE001
        result["probe_error"] = f"{type(exc).__name__}: {exc}"
    return result
