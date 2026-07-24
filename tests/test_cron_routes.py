"""app/api/routes/cron.py: the Vercel Cron-triggered equivalents of
services/scheduler.py's background loops. See docs/vercel-deployment.md.
"""

import pytest
from app.api.routes import cron
from app.config import Settings, get_settings
from app.main import app
from httpx import ASGITransport, AsyncClient

AUTHORIZED = {"Authorization": "Bearer test-cron-secret"}


def _settings_with_secret() -> Settings:
    return Settings(_env_file=None, cron_secret="test-cron-secret")


class _FakeDailySellerScheduler:
    async def run_once(self) -> list[dict[str, object]]:
        return [{"org_id": "org_test_seller", "discord_sent": True}]


class _FakeSingleReportScheduler:
    async def run_once(self) -> bool:
        return True


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_daily_seller_reports_cron_rejects_missing_secret() -> None:
    app.dependency_overrides[get_settings] = _settings_with_secret
    try:
        async with await _client() as client:
            response = await client.get("/internal/cron/daily-seller-reports")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_daily_seller_reports_cron_rejects_wrong_secret() -> None:
    app.dependency_overrides[get_settings] = _settings_with_secret
    try:
        async with await _client() as client:
            response = await client.get(
                "/internal/cron/daily-seller-reports",
                headers={"Authorization": "Bearer wrong-secret"},
            )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_cron_endpoints_refuse_everything_when_secret_unset() -> None:
    """An empty CRON_SECRET must fail closed, not run open."""
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, cron_secret="")
    try:
        async with await _client() as client:
            response = await client.get(
                "/internal/cron/daily-seller-reports", headers=AUTHORIZED
            )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_daily_seller_reports_cron_runs_when_authorized() -> None:
    app.dependency_overrides[get_settings] = _settings_with_secret
    app.dependency_overrides[cron.get_daily_seller_report_scheduler] = (
        lambda: _FakeDailySellerScheduler()
    )
    try:
        async with await _client() as client:
            response = await client.get(
                "/internal/cron/daily-seller-reports", headers=AUTHORIZED
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ran"] == 1
        assert body["results"][0]["org_id"] == "org_test_seller"
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(cron.get_daily_seller_report_scheduler, None)


@pytest.mark.asyncio
async def test_platform_traffic_cron_runs_when_authorized() -> None:
    app.dependency_overrides[get_settings] = _settings_with_secret
    app.dependency_overrides[cron.get_platform_traffic_scheduler] = (
        lambda: _FakeSingleReportScheduler()
    )
    try:
        async with await _client() as client:
            response = await client.get("/internal/cron/platform-traffic", headers=AUTHORIZED)
        assert response.status_code == 200
        assert response.json() == {"discord_sent": True}
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(cron.get_platform_traffic_scheduler, None)


@pytest.mark.asyncio
async def test_monthly_market_share_cron_runs_when_authorized() -> None:
    app.dependency_overrides[get_settings] = _settings_with_secret
    app.dependency_overrides[cron.get_seller_market_share_scheduler] = (
        lambda: _FakeSingleReportScheduler()
    )
    try:
        async with await _client() as client:
            response = await client.get(
                "/internal/cron/monthly-market-share", headers=AUTHORIZED
            )
        assert response.status_code == 200
        assert response.json() == {"discord_sent": True}
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(cron.get_seller_market_share_scheduler, None)
