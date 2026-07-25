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


_CANCELLABLE_ORDER_STATUSES = {"PENDING_PAYMENT", "PREPARING"}


@router.post("/reply", response_model=AIReplyResponse)
async def create_reply(
    payload: AIReplyRequest,
    service: Annotated[OpenRouterSupportService, Depends(get_ai_service)],
    notifier: Annotated[DiscordNotifier, Depends(get_discord_notifier)],
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
) -> AIReplyResponse:
    response = await run_in_threadpool(service.generate_reply, payload)

    # LOW-risk order cancellation, before shipping, executes immediately
    # instead of just telling the customer it's "possible" -- code performs
    # the action (same endpoint the customer's own cancel button calls),
    # never the LLM. Only for the exact case that's already safe by the
    # site's own rules: PENDING_PAYMENT/PREPARING orders can already be
    # self-service cancelled, this just skips the click.
    order_status = str(payload.order_context.get("status") or "") if payload.order_context else ""
    auto_cancelled = False
    if (
        response.category == "CANCEL"
        and response.risk == "LOW"
        and not response.requires_human
        and payload.order_id
        and order_status in _CANCELLABLE_ORDER_STATUSES
    ):
        try:
            await commerce.cancel_order(payload.order_id, "AI 자동 취소 - 배송 전 단순 변심")
            auto_cancelled = True
        except Exception:  # noqa: BLE001 - order may have shipped meanwhile; don't break the reply
            auto_cancelled = False
        if auto_cancelled:
            response = response.model_copy(
                update={
                    "answer": response.answer
                    + "\n\n✅ 배송 전 상태로 확인되어 주문이 자동으로 취소·환불 처리되었습니다."
                }
            )

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

    # The seller's own "문의-이관" channel webhook, auto-provisioned by
    # /실행 and stored in discord_channels -- no env var, no manual setup.
    # Falls back to the platform's admin/dev webhook only when this inquiry
    # can't be attributed to a seller (no order_id) or that seller hasn't
    # linked Discord yet, so escalations never just silently vanish.
    seller_webhook_url = (
        await commerce.get_org_discord_webhook(org_id, "support") if org_id else None
    )
    target_notifier = (
        DiscordNotifier(seller_webhook_url, get_settings().discord_timeout_seconds)
        if seller_webhook_url
        else notifier
    )
    if target_notifier.enabled:
        await run_in_threadpool(
            _notify_discord, target_notifier, final, payload, inquiry_id, auto_cancelled
        )
    return final


def _notify_discord(
    notifier: DiscordNotifier,
    final: AIReplyResponse,
    payload: AIReplyRequest,
    inquiry_id: str,
    auto_cancelled: bool,
) -> bool:
    """Builds and sends the right embed for the outcome that just happened:
    an informational summary (auto-cancelled), a two-button approve/reply
    prompt (MEDIUM risk), or a single-button escalation (HIGH risk / any
    other requires_human trigger). LOW risk that wasn't auto-cancelled sends
    nothing -- routine FAQ-style answers shouldn't page a seller's Discord.
    """
    question_preview = payload.question[:300]
    if auto_cancelled:
        embed = {
            "title": "✅ 자동 처리 완료",
            "description": f"문의: {question_preview}",
            "color": 0x4ADE80,
            "fields": [
                {
                    "name": "처리 내용",
                    "value": "배송 전 주문을 자동으로 취소·환불했습니다.",
                    "inline": False,
                },
                {"name": "문의 ID", "value": inquiry_id, "inline": False},
            ],
        }
        return notifier.send_embed(embed)

    if final.requires_human:
        embed = {
            "title": "🚨 상담원 이관 필요",
            "description": f"문의: {question_preview}",
            "color": 0xF87171,
            "fields": [
                {"name": "분류", "value": final.category, "inline": True},
                {"name": "위험도", "value": final.risk, "inline": True},
                {"name": "문의 ID", "value": inquiry_id, "inline": False},
            ],
        }
        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 2,
                        "label": "답변하기",
                        "custom_id": f"reply:{inquiry_id}",
                    },
                ],
            }
        ]
        return notifier.send_embed(embed, components)

    if final.risk == "MEDIUM":
        embed = {
            "title": "🟡 확인 필요",
            "description": (
                f"문의: {question_preview}\n\n**AI 제안 답변**\n{final.answer[:600]}\n\n"
                "이런 식으로 해결해도 될까요?"
            ),
            "color": 0xFBBF24,
            "fields": [
                {"name": "분류", "value": final.category, "inline": True},
                {"name": "위험도", "value": final.risk, "inline": True},
                {"name": "문의 ID", "value": inquiry_id, "inline": False},
            ],
        }
        components = [
            {
                "type": 1,
                "components": [
                    {"type": 2, "style": 3, "label": "승인", "custom_id": f"approve:{inquiry_id}"},
                    {"type": 2, "style": 2, "label": "답변", "custom_id": f"reply:{inquiry_id}"},
                ],
            }
        ]
        return notifier.send_embed(embed, components)

    return False


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
