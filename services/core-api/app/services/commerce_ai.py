import json
from contextlib import nullcontext
from typing import Any

from langfuse import propagate_attributes

from app.config import Settings
from app.schemas.ai import CommerceInsightResponse, MonthlyReportResponse
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
