import json
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from langfuse import propagate_attributes

from app.config import Settings
from app.schemas.ai import AIReplyRequest, AIReplyResponse
from app.services import personas
from app.services.llm_client import build_openrouter_client
from app.services.prompts import CompiledPrompt, PromptRepository

HUMAN_HANDOFF_KEYWORDS = ("분쟁", "소송", "신고", "고액 환불", "개인정보 유출")

# customer-support-answer.md rule 4 tells the answer persona to say a human
# handoff is needed whenever cancel/refund *execution* requires approval --
# independent of whether the question itself hit a HIGH-risk keyword above
# (a plain "취소하고 싶어요" isn't a dispute/lawsuit/report, so triage alone
# never flags it). Without this check the customer is told "상담원에게
# 연결해 드릴게요" but no one is ever actually notified.
def _answer_promises_handoff(answer: str) -> bool:
    return "상담원" in answer and ("이관" in answer or "연결" in answer)


_CATEGORIES = ("DELIVERY", "CANCEL", "REFUND", "OTHER")
_RISKS = ("LOW", "MEDIUM", "HIGH")


@dataclass(slots=True)
class TriageResult:
    category: str
    risk: str
    requires_human: bool
    reason: str = ""


class OpenRouterSupportService:
    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = build_openrouter_client(settings)

    def generate_reply(self, request: AIReplyRequest) -> AIReplyResponse:
        langfuse = self.prompts.langfuse
        attributes_context: Any = nullcontext()
        if langfuse is not None:
            attributes_context = propagate_attributes(
                user_id=request.user_id,
                session_id=request.session_id,
                tags=["customer-support", f"channel:{request.channel}"],
                environment=self.settings.app_env,
            )

        with attributes_context:
            root_context: Any = nullcontext()
            if langfuse is not None:
                trace_context = None
                if request.request_id:
                    trace_context = {"trace_id": langfuse.create_trace_id(seed=request.request_id)}
                root_context = langfuse.start_as_current_observation(
                    as_type="span",
                    name="answer-customer-inquiry",
                    trace_context=trace_context,
                    input=request.question,
                    metadata={
                        "request_id": request.request_id,
                        "order_id": request.order_id,
                        "organization_id": request.organization_id,
                        "channel": request.channel,
                    },
                )

            with root_context as root_span:
                response = self._run_pipeline(request)
                if root_span is not None:
                    root_span.update(
                        output=response.answer,
                        metadata={
                            "model": response.model,
                            "requires_human": response.requires_human,
                            "prompt_source": response.prompt_source,
                            "prompt_version": response.prompt_version,
                            "category": response.category,
                            "risk": response.risk,
                        },
                    )
                    return response.model_copy(update={"trace_id": root_span.trace_id})
                return response

    def _run_pipeline(self, request: AIReplyRequest) -> AIReplyResponse:
        triage = self._classify_inquiry(request)
        compiled = self._compile_prompt(request)
        question_flagged = triage.requires_human or any(
            keyword in request.question for keyword in HUMAN_HANDOFF_KEYWORDS
        )

        if self.client is None:
            return AIReplyResponse(
                answer=(
                    "OPENROUTER_API_KEY가 설정되지 않았습니다. "
                    "현재 문의는 상담원에게 이관합니다."
                ),
                model=compiled.model,
                prompt_source=compiled.source,
                prompt_version=compiled.version,
                requires_human=True,
                category=triage.category,
                risk=triage.risk,
            )

        answer, resolved_model = self._generate_with_openrouter(request, compiled)
        # OR'd with the question-side check rather than replacing it -- a
        # HIGH-risk question must still escalate even if the model's answer
        # happens not to repeat the handoff phrasing this time.
        requires_human = question_flagged or _answer_promises_handoff(answer)
        return AIReplyResponse(
            answer=answer,
            model=resolved_model,
            prompt_source=compiled.source,
            prompt_version=compiled.version,
            requires_human=requires_human,
            category=triage.category,
            risk=triage.risk,
        )

    def _classify_inquiry(self, request: AIReplyRequest) -> TriageResult:
        """support-triage persona: category + risk classification.

        Runs as its own nested Langfuse span ("classify-inquiry") ahead of
        the actual reply generation, so the pipeline mirrors the "문의 분류
        → 주문 조회 → 정책 검증 → OpenRouter 답변" workflow steps rather than
        collapsing everything into one call.
        """
        langfuse = self.prompts.langfuse
        triage_context: Any = nullcontext()
        if langfuse is not None:
            triage_context = langfuse.start_as_current_observation(
                as_type="span",
                name="classify-inquiry",
                input=request.question,
            )

        with triage_context as triage_span:
            compiled = self.prompts.compile(
                prompt_name=self.settings.langfuse_triage_prompt_name,
                fallback_text=personas.SUPPORT_TRIAGE.fallback_text,
                fallback_config=personas.SUPPORT_TRIAGE.fallback_config,
                variables={"question": request.question},
            )
            result = self._keyword_triage(request.question)
            if self.client is not None:
                try:
                    completion = self.client.chat.completions.create(
                        model=compiled.model,
                        messages=[{"role": "user", "content": compiled.text}],
                        extra_body=compiled.routing_parameters or None,
                        **compiled.completion_parameters,
                        name="classify-support-inquiry",
                        metadata={
                            "feature": "support-triage",
                            "prompt_name": compiled.name,
                            "prompt_source": compiled.source,
                            "request_id": request.request_id,
                        },
                    )
                    raw = completion.choices[0].message.content or ""
                    parsed = self._parse_triage_json(raw)
                    if parsed is not None:
                        result = parsed
                except Exception:
                    pass
            if triage_span is not None:
                triage_span.update(
                    output={
                        "category": result.category,
                        "risk": result.risk,
                        "requires_human": result.requires_human,
                    }
                )
            return result

    @staticmethod
    def _keyword_triage(question: str) -> TriageResult:
        if any(word in question for word in ("배송", "도착", "택배")):
            category = "DELIVERY"
        elif any(word in question for word in ("취소", "철회")):
            category = "CANCEL"
        elif any(word in question for word in ("환불", "반품", "교환")):
            category = "REFUND"
        else:
            category = "OTHER"
        risk = "HIGH" if any(word in question for word in HUMAN_HANDOFF_KEYWORDS) else "LOW"
        return TriageResult(
            category=category,
            risk=risk,
            requires_human=risk == "HIGH",
            reason="keyword-fallback",
        )

    @staticmethod
    def _parse_triage_json(raw: str) -> TriageResult | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[-1] if "\n" in text else text
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        category = str(data.get("category", "OTHER")).upper()
        if category not in _CATEGORIES:
            category = "OTHER"
        risk = str(data.get("risk", "LOW")).upper()
        if risk not in _RISKS:
            risk = "LOW"
        requires_human = bool(data.get("requires_human", risk == "HIGH"))
        reason = str(data.get("reason", ""))[:300]
        return TriageResult(
            category=category, risk=risk, requires_human=requires_human, reason=reason
        )

    def _compile_prompt(self, request: AIReplyRequest) -> CompiledPrompt:
        order_context = json.dumps(
            request.order_context,
            ensure_ascii=False,
            default=str,
        )
        langfuse = self.prompts.langfuse
        prompt_context: Any = nullcontext()
        if langfuse is not None:
            prompt_context = langfuse.start_as_current_observation(
                as_type="retriever",
                name="retrieve-support-prompt",
                input={"prompt_name": self.settings.langfuse_support_prompt_name},
            )

        with prompt_context as prompt_span:
            compiled = self.prompts.compile(
                prompt_name=self.settings.langfuse_support_prompt_name,
                fallback_text=personas.SUPPORT_ANSWER.fallback_text,
                fallback_config=personas.SUPPORT_ANSWER.fallback_config,
                variables={
                    "question": request.question,
                    "order_context": order_context or "주문 정보 없음",
                    "policy_context": request.policy_context or "등록된 정책 정보 없음",
                },
            )
            if prompt_span is not None:
                prompt_span.update(
                    output={
                        "name": compiled.name,
                        "source": compiled.source,
                        "version": compiled.version,
                        "model": compiled.model,
                    }
                )
            return compiled

    def _generate_with_openrouter(
        self,
        request: AIReplyRequest,
        compiled: CompiledPrompt,
    ) -> tuple[str, str]:
        extra: dict[str, Any] = {
            "name": "generate-support-reply",
            "metadata": {
                "feature": "customer-support",
                "prompt_name": compiled.name,
                "prompt_source": compiled.source,
                "request_id": request.request_id,
            },
        }
        if compiled.langfuse_prompt is not None:
            extra["langfuse_prompt"] = compiled.langfuse_prompt

        completion = self.client.chat.completions.create(
            model=compiled.model,
            messages=[{"role": "user", "content": compiled.text}],
            extra_body=compiled.routing_parameters or None,
            **compiled.completion_parameters,
            **extra,
        )
        answer = completion.choices[0].message.content or "답변을 생성하지 못했습니다."
        return answer, completion.model or compiled.model
