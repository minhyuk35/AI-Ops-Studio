from types import SimpleNamespace

from app.config import Settings
from app.schemas.ai import AIReplyRequest
from app.services import personas
from app.services.openrouter import OpenRouterSupportService
from app.services.prompts import CompiledPrompt, PromptRepository
from app.services.tracing import redact_sensitive_text


def test_redact_sensitive_text() -> None:
    text = "demo@example.com 010-1234-5678 4111 1111 1111 1111"
    assert redact_sensitive_text(text) == ("[REDACTED EMAIL] [REDACTED PHONE] [REDACTED CARD]")


def test_prompt_config_uses_openrouter_runtime_defaults() -> None:
    settings = Settings(
        _env_file=None,
        openrouter_default_model="~google/gemini-flash-latest",
        langfuse_public_key="",
        langfuse_secret_key="",
    )
    compiled = PromptRepository(settings).compile(
        prompt_name="customer-support-answer",
        fallback_text=personas.SUPPORT_ANSWER.fallback_text,
        fallback_config=personas.SUPPORT_ANSWER.fallback_config,
        variables={
            "question": "배송이 언제 도착하나요?",
            "order_context": '{"status":"SHIPPING"}',
            "policy_context": "배송 예정일만 안내합니다.",
        },
    )

    assert compiled.name == "customer-support-answer"
    assert compiled.model == "~google/gemini-flash-latest"
    assert compiled.completion_parameters == {"temperature": 0.2, "max_tokens": 700}
    assert compiled.routing_parameters == {
        "provider": {"allow_fallbacks": True, "data_collection": "deny"}
    }


def test_openrouter_call_uses_prompt_runtime_config() -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="배송 예정일은 내일입니다."))
                ],
                model="google/gemini-3.5-flash",
            )

    settings = Settings(
        _env_file=None,
        openrouter_api_key="",
        langfuse_public_key="",
        langfuse_secret_key="",
    )
    prompts = PromptRepository(settings)
    service = OpenRouterSupportService(settings, prompts)
    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    compiled = CompiledPrompt(
        text="테스트 프롬프트",
        name="customer-support-answer",
        source="langfuse",
        version="2",
        config={
            "gateway": "openrouter",
            "model": "~google/gemini-flash-latest",
            "temperature": 0.15,
            "max_tokens": 512,
            "provider": {"allow_fallbacks": True, "data_collection": "deny"},
        },
    )

    answer, resolved_model = service._generate_with_openrouter(
        AIReplyRequest(question="배송 예정일을 알려주세요."),
        compiled,
    )

    assert captured["model"] == "~google/gemini-flash-latest"
    assert captured["temperature"] == 0.15
    assert captured["max_tokens"] == 512
    assert captured["extra_body"] == {
        "provider": {"allow_fallbacks": True, "data_collection": "deny"}
    }
    assert answer == "배송 예정일은 내일입니다."
    assert resolved_model == "google/gemini-3.5-flash"
