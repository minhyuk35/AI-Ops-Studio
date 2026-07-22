from dataclasses import dataclass
from typing import Any

from langfuse import Langfuse

from app.config import Settings
from app.services.tracing import mask_otel_spans

FALLBACK_PROMPT = """당신은 쇼핑몰 고객지원 AI입니다.

고객 문의:
{{question}}

주문 정보:
{{order_context}}

정책 정보:
{{policy_context}}

규칙:
1. 제공된 주문 정보와 정책만 사용하세요.
2. 확인되지 않은 배송일, 환불 가능 여부, 금액을 추측하지 마세요.
3. 개인정보를 답변에 불필요하게 노출하지 마세요.
4. 정보가 부족하거나 취소·환불 실행 승인이 필요하면 상담원 이관이 필요하다고 명시하세요.
5. 답변은 간결하고 친절한 한국어로 작성하세요.
"""


@dataclass(slots=True)
class CompiledPrompt:
    text: str
    source: str
    version: str | None
    langfuse_prompt: Any | None = None


class PromptRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._langfuse = (
            Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                base_url=settings.langfuse_base_url,
                environment=settings.app_env,
                release=settings.app_version,
                sample_rate=settings.langfuse_sample_rate,
                mask_otel_spans=mask_otel_spans,
            )
            if settings.langfuse_enabled
            else None
        )

    def compile(self, *, question: str, order_context: str, policy_context: str) -> CompiledPrompt:
        variables = {
            "question": question,
            "order_context": order_context,
            "policy_context": policy_context or "등록된 정책 정보 없음",
        }

        if self._langfuse is not None:
            try:
                prompt = self._langfuse.get_prompt(
                    self.settings.langfuse_prompt_name,
                    type="text",
                    label=self.settings.langfuse_prompt_label,
                    cache_ttl_seconds=self.settings.langfuse_prompt_cache_ttl_seconds,
                    fallback=FALLBACK_PROMPT,
                )
                source = "fallback" if getattr(prompt, "is_fallback", False) else "langfuse"
                version = getattr(prompt, "version", None)
                return CompiledPrompt(
                    text=prompt.compile(**variables),
                    source=source,
                    version=str(version) if version is not None else None,
                    langfuse_prompt=None if getattr(prompt, "is_fallback", False) else prompt,
                )
            except Exception:
                pass

        text = FALLBACK_PROMPT
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", value)
        return CompiledPrompt(
            text=text,
            source="fallback",
            version=None,
            langfuse_prompt=None,
        )

    @property
    def langfuse(self):
        return self._langfuse
