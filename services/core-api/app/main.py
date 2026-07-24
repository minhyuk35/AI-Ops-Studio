from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai, health, inquiries, ops, revenue
from app.config import get_settings
from app.services.commerce_ai import SellerDailyReportService
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier
from app.services.inquiry_store import inquiry_store
from app.services.prompts import PromptRepository, get_shared_langfuse
from app.services.scheduler import DailySellerReportScheduler

settings = get_settings()
scheduler = DailySellerReportScheduler(
    settings,
    CommerceClient(settings),
    SellerDailyReportService(settings, PromptRepository(settings)),
    DiscordNotifier(settings),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    inquiry_store.initialize()
    ops.ops_store.initialize()
    scheduler.start()
    yield
    scheduler.stop()
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
