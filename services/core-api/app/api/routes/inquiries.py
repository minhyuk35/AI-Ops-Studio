from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.routes.revenue import get_commerce_client
from app.services.commerce_client import CommerceClient
from app.services.identity import require_org_access
from app.services.inquiry_store import inquiry_store

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


class InquiryUpdate(BaseModel):
    status: Literal["ESCALATED", "RESOLVED"]
    note: str | None = Field(default=None, max_length=1000)


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
