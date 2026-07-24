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
        period = datetime.now(UTC).strftime("%Y-%m")
        # The daily-seller-report demo seed (org_test_seller2) already books
        # revenue "today", so this period is never a clean-slate zero in a
        # freshly initialized db — assert the delta this order adds instead.
        baseline = (await client.get("/analytics/summary", params={"period": period})).json()
        order = await _pay_for_one_unit(client, "var_004_m", "cart_summary_a")
        summary = (await client.get("/analytics/summary", params={"period": period})).json()

        assert summary["gross_revenue"] - baseline["gross_revenue"] == order["total"]
        assert summary["refund_amount"] == baseline["refund_amount"]
        assert summary["net_revenue"] - baseline["net_revenue"] == order["total"]
        assert summary["order_count"] - baseline["order_count"] == 1


@pytest.mark.asyncio
async def test_revenue_summary_nets_out_a_same_month_cancellation(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        period = datetime.now(UTC).strftime("%Y-%m")
        baseline = (await client.get("/analytics/summary", params={"period": period})).json()
        order = await _pay_for_one_unit(client, "var_005_one", "cart_summary_b")
        await client.post(f"/orders/{order['id']}/cancel", json={"reason": "단순 변심"})
        summary = (await client.get("/analytics/summary", params={"period": period})).json()

        assert summary["gross_revenue"] - baseline["gross_revenue"] == order["total"]
        assert summary["refund_amount"] - baseline["refund_amount"] == order["total"]
        assert summary["net_revenue"] == baseline["net_revenue"]


@pytest.mark.asyncio
async def test_product_breakdown_includes_zero_sale_products(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        # var_002_iv belongs to prd_002 (Canvas Daily Bag) at 42,000 won/unit.
        await _pay_for_one_unit(client, "var_002_iv", "cart_products_a")

        period = datetime.now(UTC).strftime("%Y-%m")
        products = (await client.get("/analytics/products", params={"period": period})).json()

        by_id = {row["product_id"]: row for row in products}
        # Every product in the catalog is represented, sold or not — the
        # exact count includes the seeded test-seller's products too, so
        # this only pins the fixed demo catalog's IDs rather than a total.
        assert {"prd_001", "prd_002", "prd_003", "prd_004", "prd_005", "prd_006"} <= by_id.keys()

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
    period = datetime.now(UTC).strftime("%Y-%m")
    with db.transaction() as connection:
        baseline = analytics.revenue_summary(connection, period)
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
        result = analytics.revenue_summary(connection, period)

    assert result["gross_revenue"] - baseline["gross_revenue"] == 50_000
    assert result["refund_amount"] - baseline["refund_amount"] == 20_000
    assert result["net_revenue"] - baseline["net_revenue"] == 30_000


def test_previous_period_wraps_across_year_boundary(commerce_app) -> None:
    _db, _main, analytics = commerce_app
    assert analytics.previous_period("2026-01") == "2025-12"
    assert analytics.previous_period("2026-07") == "2026-06"
