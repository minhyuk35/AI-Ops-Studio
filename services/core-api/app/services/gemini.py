import json
from contextlib import nullcontext
from typing import Any

from google import genai
from langfuse import propagate_attributes

from app.config import Settings
from app.schemas.ai import AIReplyRequest, AIReplyResponse
from app.services.prompts import CompiledPrompt, PromptRepository

HUMAN_HANDOFF_KEYWORDS = ("분쟁", "소송", "신고", "고액 환불", "개인정보 유출")


class GeminiSupportService:
    def __init__(self, settings: Settings, prompts: PromptRepository) -> None:
        self.settings = settings
        self.prompts = prompts
        self.client = (
            genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
        )

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
                            "requires_human": response.requires_human,
                            "prompt_source": response.prompt_source,
                            "prompt_version": response.prompt_version,
                        },
                    )
                    return response.model_copy(update={"trace_id": root_span.trace_id})
                return response

    def _run_pipeline(self, request: AIReplyRequest) -> AIReplyResponse:
        compiled = self._compile_prompt(request)
        requires_human = any(keyword in request.question for keyword in HUMAN_HANDOFF_KEYWORDS)

        if self.client is None:
            return AIReplyResponse(
                answer=("GEMINI_API_KEY가 설정되지 않았습니다. 현재 문의는 상담원에게 이관합니다."),
                model=self.settings.gemini_model,
                prompt_source=compiled.source,
                prompt_version=compiled.version,
                requires_human=True,
            )

        answer = self._generate_with_gemini(request, compiled)
        return AIReplyResponse(
            answer=answer,
            model=self.settings.gemini_model,
            prompt_source=compiled.source,
            prompt_version=compiled.version,
            requires_human=requires_human,
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
                input={"prompt_name": self.settings.langfuse_prompt_name},
            )

        with prompt_context as prompt_span:
            compiled = self.prompts.compile(
                question=request.question,
                order_context=order_context or "주문 정보 없음",
                policy_context=request.policy_context,
            )
            if prompt_span is not None:
                prompt_span.update(
                    output={
                        "source": compiled.source,
                        "version": compiled.version,
                    }
                )
            return compiled

    def _generate_with_gemini(
        self,
        request: AIReplyRequest,
        compiled: CompiledPrompt,
    ) -> str:
        langfuse = self.prompts.langfuse
        generation_context: Any = nullcontext()
        if langfuse is not None:
            generation_context = langfuse.start_as_current_observation(
                as_type="generation",
                name="generate-support-reply",
                model=self.settings.gemini_model,
                input=[{"role": "user", "content": compiled.text}],
                prompt=compiled.langfuse_prompt,
                metadata={
                    "prompt_source": compiled.source,
                    "request_id": request.request_id,
                },
            )

        with generation_context as generation:
            interaction = self.client.interactions.create(
                model=self.settings.gemini_model,
                input=compiled.text,
            )
            answer = interaction.output_text or "답변을 생성하지 못했습니다."
            if generation is not None:
                generation.update(
                    output=[{"role": "assistant", "content": answer}],
                    usage_details=self._usage_details(interaction.usage),
                    metadata={"interaction_id": interaction.id},
                )
            return answer

    @staticmethod
    def _usage_details(usage: Any) -> dict[str, int] | None:
        if usage is None:
            return None

        cached = int(usage.total_cached_tokens or 0)
        input_total = int(usage.total_input_tokens or 0)
        output = int(usage.total_output_tokens or 0)
        thought = int(usage.total_thought_tokens or 0)
        tool_use = int(usage.total_tool_use_tokens or 0)
        total = int(usage.total_tokens or 0)

        details: dict[str, int] = {}
        if input_total:
            details["input"] = max(input_total - cached, 0)
        if cached:
            details["input_cached_tokens"] = cached
        if output:
            details["output"] = output
        if thought:
            details["output_reasoning_tokens"] = thought
        if tool_use:
            details["input_tool_use_tokens"] = tool_use
        if total:
            details["total"] = total
        return details or None
