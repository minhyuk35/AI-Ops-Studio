from typing import Any

import httpx

from app.config import Settings


class CommerceClient:
    """Thin proxy over mock-commerce-api's analytics, identity and org endpoints.

    Numbers are computed once, in the service that owns the commerce event
    ledger (services/mock-commerce-api/app/analytics.py). Core API forwards
    them to Ops Console rather than recomputing, so there is a single source
    of truth for revenue math.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.mock_commerce_api_url.rstrip("/")
        self._timeout = settings.mock_commerce_timeout_seconds

    async def get_revenue_summary(self, period: str | None) -> dict[str, object]:
        return await self._get("/analytics/summary", {"period": period} if period else None)

    async def get_product_breakdown(self, period: str | None) -> list[dict[str, object]]:
        return await self._get("/analytics/products", {"period": period} if period else None)

    async def get_seller_daily_snapshot(self, org_id: str, date: str | None) -> dict[str, object]:
        params: dict[str, str] = {"org_id": org_id}
        if date:
            params["date"] = date
        return await self._get("/analytics/seller-daily", params)

    async def list_active_organizations(self) -> list[dict[str, object]]:
        return await self._get("/internal/organizations", None)

    async def get_order_org_id(self, order_id: str) -> str | None:
        """Best-effort: an unreachable commerce API must never break a reply.

        Org attribution on an inquiry is an enrichment, not a requirement —
        if this lookup fails for any reason, the inquiry still saves, it
        just falls back to the platform-wide inbox instead of a seller's.
        """
        try:
            data = await self._get(f"/internal/orders/{order_id}/org", None)
        except httpx.HTTPError:
            return None
        return str(data["org_id"])

    async def verify_identity(self, token: str) -> dict[str, object] | None:
        """Resolve a customer JWT to their profile (id, role, organization).

        Used to authorize seller-scoped endpoints: core-api never decodes or
        trusts the JWT itself, it just asks mock-commerce-api (the service
        that actually owns customer identity) whose token this is.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(
                "/customers/me", headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code == 401:
                return None
            response.raise_for_status()
            return response.json()

    async def _get(self, path: str, params: dict[str, str] | None) -> Any:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
