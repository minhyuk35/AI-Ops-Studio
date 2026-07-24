from types import SimpleNamespace

from app.config import Settings
from app.schemas.ai import AIReplyRequest
from app.services.commerce_ai import CommerceInsightService, MonthlyReportService
from app.services.discord import DiscordNotifier
from app.services.openrouter import OpenRouterSupportService, TriageResult
from app.services.prompts import PromptRepository

NO_LANGFUSE = {"langfuse_public_key": "", "langfuse_secret_key": ""}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **NO_LANGFUSE, **overrides)


def test_parse_triage_json_extracts_object_from_code_fence() -> None:
    raw = (
        '```json\n{"category": "refund", "risk": "high", '
        '"requires_human": true, "reason": "고액 환불"}\n```'
    )
    result = OpenRouterSupportService._parse_triage_json(raw)
    assert result == TriageResult(
        category="REFUND", risk="HIGH", requires_human=True, reason="고액 환불"
    )


def test_parse_triage_json_returns_none_for_garbage() -> None:
    assert OpenRouterSupportService._parse_triage_json("이건 JSON이 아닙니다") is None


def test_parse_triage_json_rejects_unknown_category() -> None:
    result = OpenRouterSupportService._parse_triage_json('{"category": "BANANA"}')
    assert result is not None
    assert result.category == "OTHER"
    assert result.risk == "LOW"


def test_keyword_triage_flags_sensitive_keywords_as_high_risk() -> None:
    result = OpenRouterSupportService._keyword_triage("고액 환불 요청이며 소송까지 고려 중입니다")
    assert result.risk == "HIGH"
    assert result.requires_human is True
    assert result.category == "REFUND"


def test_classify_inquiry_falls_back_to_keywords_without_api_key() -> None:
    settings = _settings(openrouter_api_key="")
    service = OpenRouterSupportService(settings, PromptRepository(settings))
    triage = service._classify_inquiry(AIReplyRequest(question="배송이 언제 도착하나요?"))
    assert triage.category == "DELIVERY"
    assert triage.risk == "LOW"


def test_reply_pipeline_carries_triage_category_through() -> None:
    settings = _settings(openrouter_api_key="")
    service = OpenRouterSupportService(settings, PromptRepository(settings))
    response = service.generate_reply(AIReplyRequest(question="배송이 언제 도착하나요?"))
    assert response.category == "DELIVERY"
    assert response.requires_human is True


def test_commerce_insight_reports_missing_api_key_without_crashing() -> None:
    settings = _settings(openrouter_api_key="")
    service = CommerceInsightService(settings, PromptRepository(settings))
    result = service.generate_insight(
        "2026-07",
        {"gross_revenue": 100000, "order_count": 3},
        [{"product_id": "p1", "product_name": "테스트 상품", "units_sold": 2}],
    )
    assert result.period == "2026-07"
    assert "OPENROUTER_API_KEY" in result.insight
    assert result.prompt_source == "fallback"


def test_monthly_report_falls_back_when_api_key_missing() -> None:
    settings = _settings(openrouter_api_key="")
    service = MonthlyReportService(settings, PromptRepository(settings))
    result = service.generate_report("2026-07", {"gross_revenue": 100000}, "인사이트 없음")
    assert result.period == "2026-07"
    assert "2026-07" in result.report
    assert result.discord_sent is False


def test_commerce_insight_uses_openrouter_when_client_available() -> None:
    settings = _settings(openrouter_api_key="")
    service = CommerceInsightService(settings, PromptRepository(settings))
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="- 매출이 늘었습니다."))]
            )

    service.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    result = service.generate_insight("2026-07", {"gross_revenue": 100000}, [])
    assert result.insight == "- 매출이 늘었습니다."
    assert captured["name"] == "generate-commerce-insight"
    assert captured["metadata"]["feature"] == "commerce-insight"


def test_discord_notifier_disabled_without_webhook_url() -> None:
    notifier = DiscordNotifier("")
    assert notifier.enabled is False
    assert notifier.send("hello") is False


def test_discord_notifier_posts_to_webhook_when_configured(monkeypatch) -> None:
    notifier = DiscordNotifier("https://discord.com/api/webhooks/test")
    assert notifier.enabled is True

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.services.discord.httpx.post", fake_post)
    assert notifier.send("월간 리포트입니다") is True
    assert captured["url"] == "https://discord.com/api/webhooks/test"
    assert captured["json"] == {"content": "월간 리포트입니다"}
