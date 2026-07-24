"""Seller-console auth guard and the daily-seller-report persona (core-api side)."""

import pytest
from app.config import Settings
from app.services.commerce_ai import SellerDailyReportService
from app.services.identity import require_identity, require_org_access
from app.services.prompts import PromptRepository
from fastapi import HTTPException

NO_LANGFUSE = {"langfuse_public_key": "", "langfuse_secret_key": ""}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **NO_LANGFUSE, **overrides)


class FakeCommerceClient:
    def __init__(self, profile: dict | None) -> None:
        self._profile = profile
        self.seen_token: str | None = None

    async def verify_identity(self, token: str) -> dict | None:
        self.seen_token = token
        return self._profile


SELLER_PROFILE = {
    "id": "cus_seller",
    "role": "SELLER",
    "organization": {"id": "org_mine", "name": "내 상점"},
}
ADMIN_PROFILE = {"id": "cus_admin", "role": "ADMIN", "organization": None}


@pytest.mark.asyncio
async def test_require_identity_rejects_missing_authorization_header() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_identity(None, FakeCommerceClient(SELLER_PROFILE))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_identity_rejects_token_commerce_api_does_not_recognize() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_identity("Bearer bad-token", FakeCommerceClient(None))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_seller_can_access_their_own_org() -> None:
    profile = await require_org_access(
        "org_mine", "Bearer good-token", FakeCommerceClient(SELLER_PROFILE)
    )
    assert profile["id"] == "cus_seller"


@pytest.mark.asyncio
async def test_seller_cannot_access_a_different_org() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_org_access(
            "org_someone_else", "Bearer good-token", FakeCommerceClient(SELLER_PROFILE)
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_any_org() -> None:
    profile = await require_org_access(
        "org_anything", "Bearer admin-token", FakeCommerceClient(ADMIN_PROFILE)
    )
    assert profile["role"] == "ADMIN"


def test_seller_daily_report_falls_back_without_api_key() -> None:
    settings = _settings(openrouter_api_key="")
    service = SellerDailyReportService(settings, PromptRepository(settings))
    snapshot = {
        "date": "2026-07-24",
        "org_id": "org_mood",
        "org_name": "무드 스토리",
        "revenue": {
            "gross_revenue": 100000, "refund_amount": 0, "net_revenue": 100000, "order_count": 2,
        },
        "products": [
            {"product_id": "p1", "product_name": "니트", "stock": 0, "views": 10, "units_sold": 1,
             "revenue": 50000, "refund_units": 0, "refund_amount": 0},
        ],
        "highlights": {
            "most_viewed": None, "least_viewed": None, "most_purchased": None,
            "most_refunded": None, "out_of_stock": [], "low_stock": [],
        },
    }
    result = service.generate_report(snapshot)
    assert result.org_id == "org_mood"
    assert result.date == "2026-07-24"
    assert "OPENROUTER_API_KEY" in result.report
    assert result.prompt_source == "fallback"
