from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from starlette.concurrency import run_in_threadpool

from app.api.routes.revenue import get_commerce_client
from app.config import get_settings
from app.schemas.ai import (
    AIReplyRequest,
    AIReplyResponse,
    CommerceInsightResponse,
    MonthlyReportRequest,
    MonthlyReportResponse,
    PlatformTrafficRequest,
    PlatformTrafficResponse,
    SellerDailyReportRequest,
    SellerDailyReportResponse,
    SellerMarketShareRequest,
    SellerMarketShareResponse,
)
from app.services.commerce_ai import (
    CommerceInsightService,
    MonthlyReportService,
    PlatformTrafficService,
    SellerDailyReportService,
    SellerMarketShareService,
)
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier
from app.services.identity import extract_token, require_admin, require_org_access
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
    settings = get_settings()
    return DiscordNotifier(settings.discord_webhook_url, settings.discord_timeout_seconds)


@lru_cache
def get_admin_discord_notifier() -> DiscordNotifier:
    settings = get_settings()
    return DiscordNotifier(settings.admin_discord_webhook_url, settings.discord_timeout_seconds)


@lru_cache
def get_seller_report_service() -> SellerDailyReportService:
    settings = get_settings()
    return SellerDailyReportService(settings, PromptRepository(settings))


@lru_cache
def get_platform_traffic_service() -> PlatformTrafficService:
    settings = get_settings()
    return PlatformTrafficService(settings, PromptRepository(settings))


@lru_cache
def get_market_share_service() -> SellerMarketShareService:
    settings = get_settings()
    return SellerMarketShareService(settings, PromptRepository(settings))


@router.post("/reply", response_model=AIReplyResponse)
async def create_reply(
    payload: AIReplyRequest,
    service: Annotated[OpenRouterSupportService, Depends(get_ai_service)],
    notifier: Annotated[DiscordNotifier, Depends(get_discord_notifier)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
) -> AIReplyResponse:
    response = await run_in_threadpool(service.generate_reply, payload)
    # Which seller does this inquiry belong to, so it shows up on *their*
    # console instead of only the platform-wide inbox — resolved from the
    # order, never trusted from the client-supplied organization_id.
    org_id = await commerce.get_order_org_id(payload.order_id) if payload.order_id else None
    inquiry_id, conversation_id = await run_in_threadpool(
        inquiry_store.save_exchange, payload, response, org_id
    )
    final = response.model_copy(
        update={
            "inquiry_id": inquiry_id,
            "conversation_id": conversation_id,
            "trace_id": response.trace_id or payload.request_id,
        }
    )
    if final.requires_human:
        message = (
            f"**상담원 이관 필요**\n분류: {final.category} · 위험도: {final.risk}\n"
            f"문의: {payload.question[:300]}\n문의 ID: {inquiry_id}"
        )
        # The seller's own "문의-이관" channel webhook, auto-provisioned by
        # /실행 and stored in discord_channels -- no env var, no manual
        # setup. Falls back to the platform's admin/dev webhook only when
        # this inquiry can't be attributed to a seller (no order_id) or
        # that seller hasn't linked Discord yet, so escalations never just
        # silently vanish.
        seller_webhook_url = (
            await commerce.get_org_discord_webhook(org_id, "support") if org_id else None
        )
        if seller_webhook_url:
            timeout = get_settings().discord_timeout_seconds
            seller_notifier = DiscordNotifier(seller_webhook_url, timeout)
            await run_in_threadpool(seller_notifier.send, message)
        elif notifier.enabled:
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


@router.post("/seller-daily-report", response_model=SellerDailyReportResponse)
async def seller_daily_report(
    payload: SellerDailyReportRequest,
    service: Annotated[SellerDailyReportService, Depends(get_seller_report_service)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    authorization: Annotated[str | None, Header()] = None,
) -> SellerDailyReportResponse:
    await require_org_access(payload.org_id, authorization, commerce)
    snapshot = await commerce.get_seller_daily_snapshot(payload.org_id, payload.date)
    report = await run_in_threadpool(service.generate_report, snapshot)
    discord_sent = False
    if payload.send_discord:
        # The seller's own linked Discord server's "일일-리포트" channel
        # webhook -- never the platform's fixed admin/test webhook, which
        # lives in a dev server no seller can see.
        webhook_url = await commerce.get_seller_discord_webhook(
            extract_token(authorization), "daily"
        )
        if webhook_url:
            message = f"**{report.org_name} · {report.date} 일일 리포트**\n\n{report.report}"
            seller_notifier = DiscordNotifier(webhook_url, get_settings().discord_timeout_seconds)
            discord_sent = await run_in_threadpool(seller_notifier.send, message)
    return report.model_copy(update={"discord_sent": discord_sent})


@router.post("/platform-daily-traffic", response_model=PlatformTrafficResponse)
async def platform_daily_traffic(
    payload: PlatformTrafficRequest,
    service: Annotated[PlatformTrafficService, Depends(get_platform_traffic_service)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    notifier: Annotated[DiscordNotifier, Depends(get_admin_discord_notifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> PlatformTrafficResponse:
    await require_admin(authorization, commerce)
    snapshot = await commerce.get_platform_daily_traffic(payload.date)
    report = await run_in_threadpool(service.generate_report, snapshot)
    discord_sent = False
    if payload.send_discord and notifier.enabled:
        message = f"**{report.date} 플랫폼 트래픽 리포트**\n\n{report.report}"
        discord_sent = await run_in_threadpool(notifier.send, message)
    return report.model_copy(update={"discord_sent": discord_sent})


@router.post("/seller-market-share", response_model=SellerMarketShareResponse)
async def seller_market_share(
    payload: SellerMarketShareRequest,
    service: Annotated[SellerMarketShareService, Depends(get_market_share_service)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    notifier: Annotated[DiscordNotifier, Depends(get_admin_discord_notifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> SellerMarketShareResponse:
    await require_admin(authorization, commerce)
    snapshot = await commerce.get_seller_market_share(payload.period)
    report = await run_in_threadpool(service.generate_report, snapshot)
    discord_sent = False
    if payload.send_discord and notifier.enabled:
        message = f"**{report.period} 판매자 매출 점유율 리포트**\n\n{report.report}"
        discord_sent = await run_in_threadpool(notifier.send, message)
    return report.model_copy(update={"discord_sent": discord_sent})
