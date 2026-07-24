from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.api.routes.revenue import get_commerce_client
from app.config import get_settings
from app.schemas.ai import (
    AIReplyRequest,
    AIReplyResponse,
    CommerceInsightResponse,
    MonthlyReportRequest,
    MonthlyReportResponse,
)
from app.services.commerce_ai import CommerceInsightService, MonthlyReportService
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier
from app.services.inquiry_store import inquiry_store
from app.services.openrouter import OpenRouterSupportService
from app.services.prompts import PromptRepository

router = APIRouter(prefix="/ai", tags=["ai"])

PERIOD_QUERY = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


def _current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


@lru_cache
def get_ai_service() -> OpenRouterSupportService:
    settings = get_settings()
    return OpenRouterSupportService(settings, PromptRepository(settings))


@lru_cache
def get_insight_service() -> CommerceInsightService:
    settings = get_settings()
    return CommerceInsightService(settings, PromptRepository(settings))


@lru_cache
def get_report_service() -> MonthlyReportService:
    settings = get_settings()
    return MonthlyReportService(settings, PromptRepository(settings))


@lru_cache
def get_discord_notifier() -> DiscordNotifier:
    return DiscordNotifier(get_settings())


@router.post("/reply", response_model=AIReplyResponse)
async def create_reply(
    payload: AIReplyRequest,
    service: Annotated[OpenRouterSupportService, Depends(get_ai_service)],
    notifier: Annotated[DiscordNotifier, Depends(get_discord_notifier)],
) -> AIReplyResponse:
    response = await run_in_threadpool(service.generate_reply, payload)
    inquiry_id, conversation_id = await run_in_threadpool(
        inquiry_store.save_exchange, payload, response
    )
    final = response.model_copy(
        update={
            "inquiry_id": inquiry_id,
            "conversation_id": conversation_id,
            "trace_id": response.trace_id or payload.request_id,
        }
    )
    if final.requires_human and notifier.enabled:
        message = (
            f"**상담원 이관 필요**\n분류: {final.category} · 위험도: {final.risk}\n"
            f"문의: {payload.question[:300]}\n문의 ID: {inquiry_id}"
        )
        await run_in_threadpool(notifier.send, message)
    return final


@router.get("/commerce-insight", response_model=CommerceInsightResponse)
async def commerce_insight(
    service: Annotated[CommerceInsightService, Depends(get_insight_service)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    period: str | None = PERIOD_QUERY,
) -> CommerceInsightResponse:
    resolved_period = period or _current_period()
    summary = await commerce.get_revenue_summary(resolved_period)
    products = await commerce.get_product_breakdown(resolved_period)
    return await run_in_threadpool(
        service.generate_insight, resolved_period, summary, products
    )


@router.post("/monthly-report", response_model=MonthlyReportResponse)
async def monthly_report(
    payload: MonthlyReportRequest,
    insight_service: Annotated[CommerceInsightService, Depends(get_insight_service)],
    report_service: Annotated[MonthlyReportService, Depends(get_report_service)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    notifier: Annotated[DiscordNotifier, Depends(get_discord_notifier)],
) -> MonthlyReportResponse:
    resolved_period = payload.period or _current_period()
    summary = await commerce.get_revenue_summary(resolved_period)
    products = await commerce.get_product_breakdown(resolved_period)
    insight = await run_in_threadpool(
        insight_service.generate_insight, resolved_period, summary, products
    )
    report = await run_in_threadpool(
        report_service.generate_report, resolved_period, summary, insight.insight
    )
    discord_sent = False
    if payload.send_discord and notifier.enabled:
        discord_sent = await run_in_threadpool(notifier.send, report.report)
    return report.model_copy(update={"discord_sent": discord_sent})
