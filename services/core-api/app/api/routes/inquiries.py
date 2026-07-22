from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.inquiry_store import inquiry_store

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


class InquiryUpdate(BaseModel):
    status: Literal["ESCALATED", "RESOLVED"]
    note: str | None = Field(default=None, max_length=1000)


@router.get("")
async def list_inquiries(
    customer_id: str | None = Query(default=None, max_length=120),
) -> list[dict[str, object]]:
    if customer_id:
        return inquiry_store.list_customer_inquiries(customer_id)
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
