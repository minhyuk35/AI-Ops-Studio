from typing import Any

import httpx

from app.config import Settings


class CommerceClient:
    """Thin proxy over mock-commerce-api's revenue analytics endpoints.

    Numbers are computed once, in the service that owns the commerce event
    ledger (services/mock-commerce-api/app/analytics.py). Core API forwards
    them to Ops Console rather than recomputing, so there is a single source
    of truth for revenue math.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.mock_commerce_api_url.rstrip("/")
        self._timeout = settings.mock_commerce_timeout_seconds

    async def get_revenue_summary(self, period: str | None) -> dict[str, object]:
        return await self._get("/analytics/summary", period)

    async def get_product_breakdown(self, period: str | None) -> list[dict[str, object]]:
        return await self._get("/analytics/products", period)

    async def _get(self, path: str, period: str | None) -> Any:
        params = {"period": period} if period else None
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
