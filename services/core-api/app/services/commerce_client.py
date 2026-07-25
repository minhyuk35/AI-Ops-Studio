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
        self._internal_token = settings.discord_bot_shared_secret

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

    async def get_platform_daily_traffic(self, date: str | None) -> dict[str, object]:
        return await self._get(
            "/analytics/platform-daily-traffic", {"date": date} if date else None
        )

    async def get_seller_market_share(self, period: str | None) -> dict[str, object]:
        return await self._get(
            "/analytics/seller-market-share", {"period": period} if period else None
        )

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

    async def cancel_order(self, order_id: str, reason: str) -> dict[str, object]:
        """Same endpoint the customer's own "주문 취소" button calls. Used by
        the support pipeline to auto-execute a LOW-risk pre-shipment
        cancellation instead of just talking about it -- raises on failure
        (e.g. the order shipped in the meantime) so the caller can decide
        whether to fall back to a human.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(f"/orders/{order_id}/cancel", json={"reason": reason})
            response.raise_for_status()
            return response.json()

    async def get_seller_discord_webhook(self, token: str, channel_key: str) -> str | None:
        """The seller's own Discord webhook for one channel (e.g. "daily"),
        set up by their own bot linking (see services/discord-bot), not the
        platform's fixed admin/test webhook. Returns None if the org hasn't
        linked Discord yet or never provisioned that channel. Used by the
        seller-facing "Discord로 전송" button, which already has the
        seller's own bearer token.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(
                "/sellers/me/discord", headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code != 200:
                return None
            return self._extract_channel_webhook(response.json(), channel_key)

    async def get_org_discord_webhook(self, org_id: str, channel_key: str) -> str | None:
        """Same lookup as get_seller_discord_webhook, but by org_id via the
        internal shared secret instead of a customer bearer token -- used by
        the scheduled daily-report cron (app/services/scheduler.py), which
        walks every active org and has neither a guild_id nor a JWT to work
        with. Returns None (silently) if DISCORD_BOT_SHARED_SECRET isn't
        configured, the org hasn't linked Discord, or that channel doesn't
        exist yet -- same as get_seller_discord_webhook's "not set up" case.
        """
        if not self._internal_token:
            return None
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(
                "/internal/discord/channels-by-org",
                params={"org_id": org_id},
                headers={"X-Internal-Token": self._internal_token},
            )
            if response.status_code != 200:
                return None
            return self._extract_channel_webhook(response.json(), channel_key)

    @staticmethod
    def _extract_channel_webhook(payload: dict[str, Any], channel_key: str) -> str | None:
        for channel in payload.get("channels", []):
            if channel.get("channel_key") == channel_key:
                webhook_url = channel.get("webhook_url")
                return str(webhook_url) if webhook_url else None
        return None

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

    async def get_product(self, product_id: str) -> dict[str, object]:
        """Public product detail lookup -- used by the AI 추천 tagger to read
        a product's name/description/material before classifying it (no
        auth needed, same endpoint the storefront's product page calls).
        """
        return await self._get(f"/products/{product_id}", None)

    async def tag_product_attributes(
        self, product_id: str, *, color_family: str, style_tags: list[str]
    ) -> None:
        """Writes back the AI 추천 tagger's one-time classification
        (docs/ai-recommendation-plan.html#s3). Internal-token authed, same
        posture as the Discord internal endpoints -- this isn't something a
        seller's own bearer token should be able to call directly.
        """
        if not self._internal_token:
            return
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.patch(
                f"/internal/products/{product_id}/attributes",
                json={"color_family": color_family, "style_tags": style_tags},
                headers={"X-Internal-Token": self._internal_token},
            )
            response.raise_for_status()

    async def _get(self, path: str, params: dict[str, str] | None) -> Any:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
