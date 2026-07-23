"""Revenue and product analytics tests for the mock-commerce-api service.

See conftest.py's ``commerce_app`` fixture docstring for why this module
loads mock-commerce-api's ``app`` package the way it does.
"""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

CHECKOUT_FIELDS = {
    "email": "buyer@example.com",
    "recipient": "김구매",
    "phone": "010-1234-5678",
    "postal_code": "04524",
    "address1": "서울특별시 중구 세종대로 110",
}


async def _client(main):
    transport = ASGITransport(app=main.app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _pay_for_one_unit(client, variant_id: str, cart_id: str) -> dict[str, object]:
    await client.post(f"/carts/{cart_id}/items", json={"variant_id": variant_id, "quantity": 1})
    order_response = await client.post(
        "/checkout/orders", json={"cart_id": cart_id, **CHECKOUT_FIELDS}
    )
    order = order_response.json()
    await client.post(
        "/payments/confirm", json={"order_id": order["id"], "amount": order["total"]}
    )
    return order


@pytest.mark.asyncio
async def test_revenue_summary_reflects_paid_orders_this_period(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        order = await _pay_for_one_unit(client, "var_004_m", "cart_summary_a")

        period = datetime.now(UTC).strftime("%Y-%m")
        summary = (await client.get("/analytics/summary", params={"period": period})).json()

        assert summary["gross_revenue"] == order["total"]
        assert summary["refund_amount"] == 0
        assert summary["net_revenue"] == order["total"]
        assert summary["order_count"] == 1
        assert summary["average_order_value"] == order["total"]
        # No paid orders exist in the previous month in this isolated test db.
        assert summary["change"]["gross_revenue_pct"] is None


@pytest.mark.asyncio
async def test_revenue_summary_nets_out_a_same_month_cancellation(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        order = await _pay_for_one_unit(client, "var_005_one", "cart_summary_b")
        await client.post(f"/orders/{order['id']}/cancel", json={"reason": "단순 변심"})

        period = datetime.now(UTC).strftime("%Y-%m")
        summary = (await client.get("/analytics/summary", params={"period": period})).json()

        assert summary["gross_revenue"] == order["total"]
        assert summary["refund_amount"] == order["total"]
        assert summary["net_revenue"] == 0


@pytest.mark.asyncio
async def test_product_breakdown_includes_zero_sale_products(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        # var_002_iv belongs to prd_002 (Canvas Daily Bag) at 42,000 won/unit.
        await _pay_for_one_unit(client, "var_002_iv", "cart_products_a")

        period = datetime.now(UTC).strftime("%Y-%m")
        products = (await client.get("/analytics/products", params={"period": period})).json()

        by_id = {row["product_id"]: row for row in products}
        assert len(products) == 6  # every seed product is represented, sold or not

        sold = by_id["prd_002"]
        assert sold["units_sold"] == 1
        assert sold["revenue"] == 42_000  # line item revenue only, unlike order total (+shipping)
        assert sold["refund_rate"] == 0.0

        untouched = by_id["prd_006"]
        assert untouched["units_sold"] == 0
        assert untouched["revenue"] == 0
        assert untouched["refund_rate"] is None


def test_revenue_summary_math_is_pure_sql_no_llm(commerce_app) -> None:
    db, _main, analytics = commerce_app
    with db.transaction() as connection:
        db.record_event(
            connection,
            event_type="PAYMENT_CONFIRMED",
            external_event_id="ord_math:PAYMENT_CONFIRMED",
            order_id="ord_math",
            amount=50_000,
        )
        db.record_event(
            connection,
            event_type="REFUND_COMPLETED",
            external_event_id="ord_math:REFUND_COMPLETED:CANCEL",
            order_id="ord_math",
            refund_amount=20_000,
        )
        period = datetime.now(UTC).strftime("%Y-%m")
        result = analytics.revenue_summary(connection, period)

    assert result["gross_revenue"] == 50_000
    assert result["refund_amount"] == 20_000
    assert result["net_revenue"] == 30_000
    assert result["average_order_value"] == 30_000


def test_previous_period_wraps_across_year_boundary(commerce_app) -> None:
    _db, _main, analytics = commerce_app
    assert analytics.previous_period("2026-01") == "2025-12"
    assert analytics.previous_period("2026-07") == "2026-06"
