from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.schemas.ai import AIReplyRequest, AIReplyResponse
from app.services.gemini import GeminiSupportService
from app.services.inquiry_store import inquiry_store
from app.services.prompts import PromptRepository

router = APIRouter(prefix="/ai", tags=["ai"])


@lru_cache
def get_ai_service() -> GeminiSupportService:
    settings = get_settings()
    return GeminiSupportService(settings, PromptRepository(settings))


@router.post("/reply", response_model=AIReplyResponse)
async def create_reply(
    payload: AIReplyRequest,
    service: Annotated[GeminiSupportService, Depends(get_ai_service)],
) -> AIReplyResponse:
    response = await run_in_threadpool(service.generate_reply, payload)
    inquiry_id, conversation_id = await run_in_threadpool(
        inquiry_store.save_exchange, payload, response
    )
    return response.model_copy(
        update={
            "inquiry_id": inquiry_id,
            "conversation_id": conversation_id,
            "trace_id": response.trace_id or payload.request_id,
        }
    )
