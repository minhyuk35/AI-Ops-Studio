import json
from contextlib import nullcontext
from typing import Any

from langfuse import propagate_attributes

from app.config import Settings
from app.schemas.ai import (
    CommerceInsightResponse,
    MonthlyReportResponse,
    PlatformTrafficResponse,
    SellerDailyReportResponse,
    SellerMarketShareResponse,
)
from app.services import personas
from app.services.llm_client import build_openrouter_client
from app.services.prompts import PromptRepository


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class CommerceInsightService:
    """commerce-insight persona: interprets numbers the code already computed.

    Never recomputes revenue math — CommerceClient's summary/product payloads
    (services/mock-commerce-api/app/analytics.py) are the single source of
    truth. This service only turns those numbers into an operator-readable
    narrative.
    """

    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = build_openrouter_client(settings)

    def generate_insight(
        self,
        period: str,
        summary: dict[str, Any],
        products: list[dict[str, Any]],
    ) -> CommerceInsightResponse:
        langfuse = self.prompts.langfuse
        attributes_context: Any = nullcontext()
        if langfuse is not None:
            attributes_context = propagate_attributes(
                session_id=f"revenue-{period}",
                tags=["commerce-insight", f"period:{period}"],
                environment=self.settings.app_env,
            )

        with attributes_context:
            root_context: Any = nullcontext()
            if langfuse is not None:
                root_context = langfuse.start_as_current_observation(
                    as_type="span",
                    name="interpret-commerce-metrics",
                    input={"period": period},
                    metadata={"order_count": summary.get("order_count")},
                )
            with root_context as root_span:
                compiled = self.prompts.compile(
                    prompt_name=self.settings.langfuse_commerce_insight_prompt_name,
                    fallback_text=personas.COMMERCE_INSIGHT.fallback_text,
                    fallback_config=personas.COMMERCE_INSIGHT.fallback_config,
                    variables={
                        "period": period,
                        "summary_json": _dump(summary),
                        "products_json": _dump(products[:20]),
                    },
                )

                if self.client is None:
                    answer = (
                        "OPENROUTER_API_KEY가 설정되지 않아 인사이트를 생성할 수 없습니다. "
                        "매출 지표는 위 표를 직접 확인해주세요."
                    )
                else:
                    completion = self.client.chat.completions.create(
                        model=compiled.model,
                        messages=[{"role": "user", "content": compiled.text}],
                        extra_body=compiled.routing_parameters or None,
                        **compiled.completion_parameters,
                        name="generate-commerce-insight",
                        metadata={
                            "feature": "commerce-insight",
                            "prompt_name": compiled.name,
                            "prompt_source": compiled.source,
                            "period": period,
                        },
                    )
                    answer = (
                        completion.choices[0].message.content or "인사이트를 생성하지 못했습니다."
                    )

                if root_span is not None:
                    root_span.update(output=answer)

                return CommerceInsightResponse(
                    period=period,
                    insight=answer,
                    model=compiled.model,
                    prompt_source=compiled.source,
                    prompt_version=compiled.version,
                )


class MonthlyReportService:
    """commerce-monthly-report persona: metrics + insight -> one publishable report."""

    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = build_openrouter_client(settings)

    def generate_report(
        self,
        period: str,
        summary: dict[str, Any],
        insight_text: str,
    ) -> MonthlyReportResponse:
        langfuse = self.prompts.langfuse
        attributes_context: Any = nullcontext()
        if langfuse is not None:
            attributes_context = propagate_attributes(
                session_id=f"revenue-{period}",
                tags=["commerce-monthly-report", f"period:{period}"],
                environment=self.settings.app_env,
            )

        with attributes_context:
            root_context: Any = nullcontext()
            if langfuse is not None:
                root_context = langfuse.start_as_current_observation(
                    as_type="span",
                    name="compose-monthly-report",
                    input={"period": period},
                )
            with root_context as root_span:
                compiled = self.prompts.compile(
                    prompt_name=self.settings.langfuse_monthly_report_prompt_name,
                    fallback_text=personas.COMMERCE_MONTHLY_REPORT.fallback_text,
                    fallback_config=personas.COMMERCE_MONTHLY_REPORT.fallback_config,
                    variables={
                        "period": period,
                        "summary_json": _dump(summary),
                        "insight_text": insight_text,
                    },
                )

                if self.client is None:
                    report = (
                        f"# {period} 월간 리포트\n\nOPENROUTER_API_KEY가 설정되지 않아 "
                        "리포트를 생성할 수 없습니다.\n\n## 인사이트\n\n" + insight_text
                    )
                else:
                    completion = self.client.chat.completions.create(
                        model=compiled.model,
                        messages=[{"role": "user", "content": compiled.text}],
                        extra_body=compiled.routing_parameters or None,
                        **compiled.completion_parameters,
                        name="generate-monthly-report",
                        metadata={
                            "feature": "commerce-monthly-report",
                            "prompt_name": compiled.name,
                            "prompt_source": compiled.source,
                            "period": period,
                        },
                    )
                    report = (
                        completion.choices[0].message.content or "리포트를 생성하지 못했습니다."
                    )

                if root_span is not None:
                    root_span.update(output=report)

                return MonthlyReportResponse(
                    period=period,
                    report=report,
                    model=compiled.model,
                    prompt_source=compiled.source,
                    prompt_version=compiled.version,
                )


class SellerDailyReportService:
    """daily-seller-report persona: one seller's daily traffic/sales/stock, narrated.

    Every number (views, units sold, refunds, stock) comes from
    mock-commerce-api's seller_daily_snapshot() — plain SQL over the
    commerce_events ledger. This service only turns that snapshot into a
    report and, specifically, the closing "AI 제안" restock feedback.
    """

    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = build_openrouter_client(settings)

    def generate_report(self, snapshot: dict[str, Any]) -> SellerDailyReportResponse:
        date = str(snapshot["date"])
        org_id = str(snapshot["org_id"])
        org_name = str(snapshot["org_name"])

        langfuse = self.prompts.langfuse
        attributes_context: Any = nullcontext()
        if langfuse is not None:
            attributes_context = propagate_attributes(
                session_id=f"seller-{org_id}-{date}",
                tags=["daily-seller-report", f"org:{org_id}"],
                environment=self.settings.app_env,
            )

        with attributes_context:
            root_context: Any = nullcontext()
            if langfuse is not None:
                root_context = langfuse.start_as_current_observation(
                    as_type="span",
                    name="compose-daily-seller-report",
                    input={"org_id": org_id, "date": date},
                )
            with root_context as root_span:
                compiled = self.prompts.compile(
                    prompt_name=self.settings.langfuse_daily_seller_report_prompt_name,
                    fallback_text=personas.DAILY_SELLER_REPORT.fallback_text,
                    fallback_config=personas.DAILY_SELLER_REPORT.fallback_config,
                    variables={
                        "org_name": org_name,
                        "date": date,
                        "revenue_json": _dump(snapshot["revenue"]),
                        "products_json": _dump(snapshot["products"]),
                        "highlights_json": _dump(snapshot["highlights"]),
                    },
                )

                if self.client is None:
                    report = (
                        f"# {org_name} 일일 리포트 ({date})\n\n"
                        "OPENROUTER_API_KEY가 설정되지 않아 리포트를 생성할 수 없습니다.\n\n"
                        f"## 매출 요약\n\n{_dump(snapshot['revenue'])}"
                    )
                else:
                    completion = self.client.chat.completions.create(
                        model=compiled.model,
                        messages=[{"role": "user", "content": compiled.text}],
                        extra_body=compiled.routing_parameters or None,
                        **compiled.completion_parameters,
                        name="generate-daily-seller-report",
                        metadata={
                            "feature": "daily-seller-report",
                            "prompt_name": compiled.name,
                            "prompt_source": compiled.source,
                            "org_id": org_id,
                            "date": date,
                        },
                    )
                    report = (
                        completion.choices[0].message.content or "리포트를 생성하지 못했습니다."
                    )

                if root_span is not None:
                    root_span.update(output=report)

                return SellerDailyReportResponse(
                    date=date,
                    org_id=org_id,
                    org_name=org_name,
                    report=report,
                    snapshot=snapshot,
                    model=compiled.model,
                    prompt_source=compiled.source,
                    prompt_version=compiled.version,
                )


class PlatformTrafficService:
    """platform-daily-traffic persona: site-wide product-view traffic, admin-only.

    Same shape of question as SellerDailyReportService ("what got looked
    at today"), but scoped to the whole platform instead of one org — which
    is exactly why it's a separate persona/prompt name rather than the same
    one called without a filter: the audience, and therefore what's safe to
    reveal, is different (a seller's own numbers vs. cross-seller traffic).
    """

    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = build_openrouter_client(settings)

    def generate_report(self, snapshot: dict[str, Any]) -> PlatformTrafficResponse:
        date = str(snapshot["date"])
        langfuse = self.prompts.langfuse
        attributes_context: Any = nullcontext()
        if langfuse is not None:
            attributes_context = propagate_attributes(
                session_id=f"platform-traffic-{date}",
                tags=["platform-daily-traffic"],
                environment=self.settings.app_env,
            )

        with attributes_context:
            root_context: Any = nullcontext()
            if langfuse is not None:
                root_context = langfuse.start_as_current_observation(
                    as_type="span",
                    name="compose-platform-traffic-report",
                    input={"date": date},
                )
            with root_context as root_span:
                compiled = self.prompts.compile(
                    prompt_name=self.settings.langfuse_platform_traffic_prompt_name,
                    fallback_text=personas.PLATFORM_DAILY_TRAFFIC.fallback_text,
                    fallback_config=personas.PLATFORM_DAILY_TRAFFIC.fallback_config,
                    variables={
                        "date": date,
                        "total_views": str(snapshot["total_views"]),
                        "top_products_json": _dump(snapshot["top_products"]),
                        "least_viewed_products_json": _dump(snapshot["least_viewed_products"]),
                        "store_ranking_json": _dump(snapshot["store_ranking"]),
                    },
                )

                if self.client is None:
                    report = (
                        f"# {date} 플랫폼 트래픽 리포트\n\n"
                        "OPENROUTER_API_KEY가 설정되지 않아 리포트를 생성할 수 없습니다."
                    )
                else:
                    completion = self.client.chat.completions.create(
                        model=compiled.model,
                        messages=[{"role": "user", "content": compiled.text}],
                        extra_body=compiled.routing_parameters or None,
                        **compiled.completion_parameters,
                        name="generate-platform-traffic-report",
                        metadata={
                            "feature": "platform-daily-traffic",
                            "prompt_name": compiled.name,
                            "prompt_source": compiled.source,
                            "date": date,
                        },
                    )
                    report = (
                        completion.choices[0].message.content or "리포트를 생성하지 못했습니다."
                    )

                if root_span is not None:
                    root_span.update(output=report)

                return PlatformTrafficResponse(
                    date=date,
                    report=report,
                    snapshot=snapshot,
                    model=compiled.model,
                    prompt_source=compiled.source,
                    prompt_version=compiled.version,
                )


class SellerMarketShareService:
    """seller-market-share-report persona: each seller's % of total platform revenue, admin-only."""

    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = build_openrouter_client(settings)

    def generate_report(self, snapshot: dict[str, Any]) -> SellerMarketShareResponse:
        period = str(snapshot["period"])
        langfuse = self.prompts.langfuse
        attributes_context: Any = nullcontext()
        if langfuse is not None:
            attributes_context = propagate_attributes(
                session_id=f"market-share-{period}",
                tags=["seller-market-share-report", f"period:{period}"],
                environment=self.settings.app_env,
            )

        with attributes_context:
            root_context: Any = nullcontext()
            if langfuse is not None:
                root_context = langfuse.start_as_current_observation(
                    as_type="span",
                    name="compose-seller-market-share-report",
                    input={"period": period},
                )
            with root_context as root_span:
                compiled = self.prompts.compile(
                    prompt_name=self.settings.langfuse_seller_market_share_prompt_name,
                    fallback_text=personas.SELLER_MARKET_SHARE.fallback_text,
                    fallback_config=personas.SELLER_MARKET_SHARE.fallback_config,
                    variables={
                        "period": period,
                        "previous_period": str(snapshot["previous_period"]),
                        "total_platform_revenue": str(snapshot["total_platform_revenue"]),
                        "platform_default_share_pct": str(snapshot["platform_default_share_pct"]),
                        "sellers_json": _dump(snapshot["sellers"]),
                    },
                )

                if self.client is None:
                    report = (
                        f"# {period} 판매자 매출 점유율 리포트\n\n"
                        "OPENROUTER_API_KEY가 설정되지 않아 리포트를 생성할 수 없습니다."
                    )
                else:
                    completion = self.client.chat.completions.create(
                        model=compiled.model,
                        messages=[{"role": "user", "content": compiled.text}],
                        extra_body=compiled.routing_parameters or None,
                        **compiled.completion_parameters,
                        name="generate-seller-market-share-report",
                        metadata={
                            "feature": "seller-market-share-report",
                            "prompt_name": compiled.name,
                            "prompt_source": compiled.source,
                            "period": period,
                        },
                    )
                    report = (
                        completion.choices[0].message.content or "리포트를 생성하지 못했습니다."
                    )

                if root_span is not None:
                    root_span.update(output=report)

                return SellerMarketShareResponse(
                    period=period,
                    report=report,
                    snapshot=snapshot,
                    model=compiled.model,
                    prompt_source=compiled.source,
                    prompt_version=compiled.version,
                )
