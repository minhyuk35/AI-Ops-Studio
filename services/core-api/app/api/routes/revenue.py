from functools import lru_cache

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.services.commerce_client import CommerceClient

router = APIRouter(prefix="/revenue", tags=["revenue"])

PERIOD_QUERY = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


@lru_cache
def get_commerce_client() -> CommerceClient:
    return CommerceClient(get_settings())


@router.get("/summary")
async def revenue_summary(period: str | None = PERIOD_QUERY) -> dict[str, object]:
    try:
        return await get_commerce_client().get_revenue_summary(period)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="커머스 API에서 매출 데이터를 가져오지 못했습니다."
        ) from exc


@router.get("/products")
async def revenue_products(period: str | None = PERIOD_QUERY) -> list[dict[str, object]]:
    try:
        return await get_commerce_client().get_product_breakdown(period)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="커머스 API에서 상품 데이터를 가져오지 못했습니다."
        ) from exc
