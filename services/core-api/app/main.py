from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai, cron, health, inquiries, ops, revenue
from app.config import get_settings, running_on_vercel
from app.services.commerce_ai import (
    PlatformTrafficService,
    SellerDailyReportService,
    SellerMarketShareService,
)
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier
from app.services.inquiry_store import inquiry_store
from app.services.prompts import PromptRepository, get_shared_langfuse
from app.services.scheduler import (
    DailySellerReportScheduler,
    PlatformTrafficScheduler,
    SellerMarketShareScheduler,
)

settings = get_settings()
_commerce = CommerceClient(settings)
_admin_notifier = DiscordNotifier(
    settings.admin_discord_webhook_url, settings.discord_timeout_seconds
)

seller_report_scheduler = DailySellerReportScheduler(
    settings,
    _commerce,
    SellerDailyReportService(settings, PromptRepository(settings)),
)
platform_traffic_scheduler = PlatformTrafficScheduler(
    settings,
    _commerce,
    PlatformTrafficService(settings, PromptRepository(settings)),
    _admin_notifier,
)
market_share_scheduler = SellerMarketShareScheduler(
    settings,
    _commerce,
    SellerMarketShareService(settings, PromptRepository(settings)),
    _admin_notifier,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    inquiry_store.initialize()
    ops.ops_store.initialize()
    # On Vercel, a Function only exists for the lifetime of one request --
    # an asyncio.create_task loop started here would be orphaned the moment
    # this invocation suspends and never wake back up. Vercel Cron Jobs call
    # app/api/routes/cron.py instead (see vercel.json); everywhere else
    # (local dev, Render/Railway/Fly.io) these background loops run as usual.
    if not running_on_vercel():
        seller_report_scheduler.start()
        platform_traffic_scheduler.start()
        market_share_scheduler.start()
    yield
    if not running_on_vercel():
        seller_report_scheduler.stop()
        platform_traffic_scheduler.stop()
        market_share_scheduler.stop()
    langfuse = get_shared_langfuse(settings)
    if langfuse is not None:
        try:
            langfuse.flush()
        except Exception:
            pass


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI Ops Studio inquiry and OpenRouter orchestration API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs", "health": "/health"}


app.include_router(health.router)
app.include_router(ai.router, prefix=settings.api_v1_prefix)
app.include_router(inquiries.router, prefix=settings.api_v1_prefix)
app.include_router(ops.router, prefix=settings.api_v1_prefix)
app.include_router(revenue.router, prefix=settings.api_v1_prefix)
app.include_router(cron.router)
