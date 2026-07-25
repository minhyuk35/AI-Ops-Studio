import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.routes.revenue import get_commerce_client
from app.config import get_settings
from app.services.commerce_client import CommerceClient
from app.services.identity import require_org_access
from app.services.inquiry_store import inquiry_store

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


class InquiryUpdate(BaseModel):
    status: Literal["ESCALATED", "RESOLVED"]
    note: str | None = Field(default=None, max_length=1000)


def _require_bot_token(x_internal_token: str | None) -> None:
    """Same shared-secret pattern as mock-commerce-api's require_internal_token
    -- gates the Discord bot's 승인 button (which can execute a real order
    cancellation) so it can't be triggered by an arbitrary POST."""
    secret = get_settings().discord_bot_shared_secret
    if not secret or not x_internal_token or not secrets.compare_digest(x_internal_token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("")
async def list_inquiries(
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    customer_id: str | None = Query(default=None, max_length=120),
    org_id: str | None = Query(default=None, max_length=64),
    authorization: Annotated[str | None, Header()] = None,
) -> list[dict[str, object]]:
    if customer_id:
        return inquiry_store.list_customer_inquiries(customer_id)
    if org_id:
        # A seller only ever sees inquiries tied to orders for their own
        # products; ADMIN can pass any org_id to inspect a specific seller.
        await require_org_access(org_id, authorization, commerce)
        return inquiry_store.list_inquiries(org_id)
    return inquiry_store.list_inquiries()


@router.get("/{inquiry_id}")
async def get_inquiry(inquiry_id: str) -> dict[str, object]:
    inquiry = inquiry_store.get_inquiry(inquiry_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    return inquiry


@router.patch("/{inquiry_id}")
async def update_inquiry(inquiry_id: str, payload: InquiryUpdate) -> dict[str, object]:
    inquiry = inquiry_store.update_status(inquiry_id, payload.status, payload.note)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    return inquiry


@router.post("/{inquiry_id}/approve")
async def approve_inquiry(
    inquiry_id: str,
    commerce: Annotated[CommerceClient, Depends(get_commerce_client)],
    x_internal_token: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """The Discord embed's "승인" button for a MEDIUM-risk inquiry: accept
    the AI's proposed answer as final. For a CANCEL-category inquiry tied to
    an order, that proposal *was* to cancel it, so approving actually calls
    the same cancel endpoint the customer's own button uses -- for every
    other category there's no generic "do whatever the AI suggested"
    executor, so approving just closes the inquiry out with that answer as
    the resolution note.
    """
    _require_bot_token(x_internal_token)
    inquiry = inquiry_store.get_inquiry(inquiry_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")

    messages = inquiry.get("messages")
    message_list = messages if isinstance(messages, list) else []
    last_answer = next(
        (
            str(message["content"])
            for message in reversed(message_list)
            if isinstance(message, dict) and message.get("role") == "assistant"
        ),
        "",
    )

    action = "RESOLVED"
    note = "판매자가 AI 제안을 승인했습니다."
    order_id = inquiry.get("order_id")
    if inquiry.get("category") == "CANCEL" and order_id:
        try:
            await commerce.cancel_order(str(order_id), "AI 제안 승인 - 판매자 승인 취소")
            action = "CANCELLED"
            note = "판매자가 승인하여 주문이 취소·환불 처리되었습니다."
        except Exception:  # noqa: BLE001 - order may no longer be cancellable; still resolve
            pass
    if last_answer:
        note = f"{note}\n\n{last_answer}"

    updated = inquiry_store.update_status(inquiry_id, "RESOLVED", note)
    return {"action": action, "inquiry": updated}
