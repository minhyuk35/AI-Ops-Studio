"""Create one real OpenRouter/Langfuse trace after credentials are configured."""

from app.config import get_settings
from app.schemas.ai import AIReplyRequest
from app.services.openrouter import OpenRouterSupportService
from app.services.prompts import PromptRepository


def main() -> None:
    settings = get_settings()
    missing = []
    if not settings.openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")
    if not settings.langfuse_public_key:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not settings.langfuse_secret_key:
        missing.append("LANGFUSE_SECRET_KEY")
    if missing:
        raise SystemExit("Set these values in .env first: " + ", ".join(missing))

    prompts = PromptRepository(settings)
    service = OpenRouterSupportService(settings, prompts)
    response = service.generate_reply(
        AIReplyRequest(
            question="배송 중인 후드티는 언제 도착하나요?",
            order_id="ord_1001",
            order_context={
                "status": "SHIPPING",
                "product_name": "Everyday Hoodie",
                "eta": "2026-07-24",
            },
            policy_context="배송 중인 주문은 확인된 배송 예정일만 안내합니다.",
            session_id="langfuse-smoke-session",
            user_id="cus_demo",
            organization_id="codilab",
            request_id="langfuse-smoke-request",
            channel="api",
        )
    )
    if prompts.langfuse is not None:
        prompts.langfuse.flush()
    print("Trace sent successfully.")
    print(f"Model: {response.model}")
    print(f"Prompt source: {response.prompt_source}")


if __name__ == "__main__":
    main()
