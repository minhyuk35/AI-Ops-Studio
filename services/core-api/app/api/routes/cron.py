"""HTTP-triggered equivalents of services/scheduler.py's background loops.

On a persistent host (local dev, Render/Railway/Fly.io), main.py's lifespan
starts three asyncio "sleep until the next scheduled hour, then run" loops
that never stop. That model doesn't work on Vercel: a serverless function
only exists for the lifetime of one request, so an asyncio.create_task loop
started on cold start is orphaned the moment the function suspends — it
never wakes back up.

These routes are the Vercel-shaped alternative: no loop, just a GET
endpoint that runs one report cycle when called, meant to be invoked by
Vercel Cron Jobs (see services/core-api/vercel.json) instead of an internal
timer. Each scheduler's own run_once() already contains the actual report
generation + Discord send logic (shared with the loop-based path), so this
file is only wiring: auth + dependency injection + calling run_once().

Cron delivery is best-effort and can occasionally double-invoke (see
Vercel's cron docs) -- run_once() re-sends a fresh report each time it's
called rather than tracking "already sent today", so a duplicate invocation
means (at most) a duplicate Discord message, never corrupted data.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.routes.ai import (
    get_admin_discord_notifier,
    get_market_share_service,
    get_platform_traffic_service,
    get_seller_report_service,
)
from app.api.routes.revenue import get_commerce_client
from app.config import Settings, get_settings
from app.services.commerce_ai import (
    PlatformTrafficService,
    SellerDailyReportService,
    SellerMarketShareService,
)
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier
from app.services.scheduler import (
    DailySellerReportScheduler,
    PlatformTrafficScheduler,
    SellerMarketShareScheduler,
)

router = APIRouter(prefix="/internal/cron", tags=["cron"])


def _verify_cron_request(authorization: str | None, settings: Settings) -> None:
    """Only Vercel Cron (or someone with the secret) may trigger these.

    Vercel automatically sends ``Authorization: Bearer $CRON_SECRET`` on
    cron-triggered requests when CRON_SECRET is set as a project env var.
    An empty/unset secret refuses every request rather than running open --
    a misconfigured deployment should fail closed, not silently accept
    unauthenticated report triggers. settings is a Depends() parameter
    (rather than calling get_settings() directly) so tests can override it.
    """
    if not settings.cron_secret or authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@lru_cache
def get_daily_seller_report_scheduler(
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    report_service: Annotated[SellerDailyReportService, Depends(get_seller_report_service)],
) -> DailySellerReportScheduler:
    return DailySellerReportScheduler(get_settings(), commerce, report_service)


@lru_cache
def get_platform_traffic_scheduler(
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    report_service: Annotated[PlatformTrafficService, Depends(get_platform_traffic_service)],
    notifier: Annotated[DiscordNotifier, Depends(get_admin_discord_notifier)],
) -> PlatformTrafficScheduler:
    return PlatformTrafficScheduler(get_settings(), commerce, report_service, notifier)


@lru_cache
def get_seller_market_share_scheduler(
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    report_service: Annotated[SellerMarketShareService, Depends(get_market_share_service)],
    notifier: Annotated[DiscordNotifier, Depends(get_admin_discord_notifier)],
) -> SellerMarketShareScheduler:
    return SellerMarketShareScheduler(get_settings(), commerce, report_service, notifier)


@router.get("/daily-seller-reports")
async def run_daily_seller_reports(
    scheduler: Annotated[
        DailySellerReportScheduler, Depends(get_daily_seller_report_scheduler)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _verify_cron_request(authorization, settings)
    results = await scheduler.run_once()
    return {"ran": len(results), "results": results}


@router.get("/platform-traffic")
async def run_platform_traffic(
    scheduler: Annotated[PlatformTrafficScheduler, Depends(get_platform_traffic_scheduler)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _verify_cron_request(authorization, settings)
    discord_sent = await scheduler.run_once()
    return {"discord_sent": discord_sent}


@router.get("/monthly-market-share")
async def run_monthly_market_share(
    scheduler: Annotated[
        SellerMarketShareScheduler, Depends(get_seller_market_share_scheduler)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _verify_cron_request(authorization, settings)
    discord_sent = await scheduler.run_once()
    return {"discord_sent": discord_sent}
