from pathlib import Path

import pytest
from app.api.routes.ai import get_ai_service
from app.config import Settings
from app.main import app
from app.services.gemini import GeminiSupportService
from app.services.inquiry_store import inquiry_store
from app.services.prompts import PromptRepository
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ai_reply_without_api_key_falls_back_to_human(tmp_path: Path) -> None:
    inquiry_store.path = tmp_path / "support.db"
    inquiry_store.initialize()
    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        langfuse_public_key="",
        langfuse_secret_key="",
    )
    service = GeminiSupportService(settings, PromptRepository(settings))
    app.dependency_overrides[get_ai_service] = lambda: service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ai/reply",
                json={
                    "question": "배송이 언제 도착하나요?",
                    "order_id": "ord_1001",
                    "order_context": {"status": "SHIPPING"},
                    "policy_context": "배송 중인 주문은 배송 예정일을 안내합니다.",
                    "session_id": "session_test",
                    "user_id": "cus_test",
                    "organization_id": "org_test",
                    "request_id": "req_test",
                    "channel": "api",
                },
            )
            inquiry_response = await client.get(
                f"/api/v1/inquiries/{response.json()['inquiry_id']}"
            )
            update_response = await client.patch(
                f"/api/v1/inquiries/{response.json()['inquiry_id']}",
                json={
                    "status": "RESOLVED",
                    "note": "상담원이 배송 예정일을 확인했습니다.",
                },
            )
    finally:
        app.dependency_overrides.pop(get_ai_service, None)

    assert response.status_code == 200
    assert response.json()["requires_human"] is True
    assert response.json()["prompt_source"] == "fallback"
    assert response.json()["inquiry_id"].startswith("inq_")

    assert inquiry_response.status_code == 200
    assert len(inquiry_response.json()["messages"]) == 2
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "RESOLVED"
    assert update_response.json()["messages"][-1]["role"] == "agent"
