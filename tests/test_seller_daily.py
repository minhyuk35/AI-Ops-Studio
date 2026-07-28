"""Daily-seller-report analytics: product views, per-org revenue, stock snapshot.

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


async def _signup_seller(client, email: str) -> dict[str, object]:
    response = await client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "correct-horse",
            "name": "김판매",
            "phone": "010-5555-6666",
            "as_seller": True,
            "shop_name": "테스트 데일리 스토어",
            "shop_category": "패션",
        },
    )
    assert response.status_code == 201
    return response.json()


async def _create_product(client, token: str, name: str, price: int, stock: int) -> dict:
    response = await client.post(
        "/sellers/me/products",
        json={
            "name": name,
            "category_id": "cat_top_tee",
            "description": "테스트 상품",
            "price": price,
            "variants": [{"color": "블랙", "size": "M", "stock": stock}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_product_view_event_is_recorded_and_scoped_to_owning_org(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        auth = await _signup_seller(client, "daily1@test.com")
        product = await _create_product(client, auth["access_token"], "뷰 테스트 상품", 30000, 10)

        for _ in range(3):
            response = await client.post(
                "/events/product-view", json={"product_id": product["id"]}
            )
            assert response.status_code == 202

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        snapshot = (
            await client.get(
                "/analytics/seller-daily",
                params={"org_id": auth["customer"]["organization"]["id"], "date": today},
            )
        ).json()

        row = next(p for p in snapshot["products"] if p["product_id"] == product["id"])
        assert row["views"] == 3
        assert row["units_sold"] == 0
        assert row["stock"] == 10


@pytest.mark.asyncio
async def test_seller_daily_snapshot_separates_revenue_by_org(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller_a = await _signup_seller(client, "daily-a@test.com")
        seller_b = await _signup_seller(client, "daily-b@test.com")
        product_a = await _create_product(client, seller_a["access_token"], "A 상품", 50000, 10)
        product_b = await _create_product(client, seller_b["access_token"], "B 상품", 20000, 10)

        for product in (product_a, product_b):
            variant_id = product["variants"][0]["id"]
            cart_id = f"cart_{product['id']}"
            await client.post(
                f"/carts/{cart_id}/items", json={"variant_id": variant_id, "quantity": 1}
            )
            order = (
                await client.post(
                    "/checkout/orders", json={"cart_id": cart_id, **CHECKOUT_FIELDS}
                )
            ).json()
            await client.post(
                "/payments/confirm", json={"order_id": order["id"], "amount": order["total"]}
            )

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        org_a_id = seller_a["customer"]["organization"]["id"]
        org_b_id = seller_b["customer"]["organization"]["id"]

        snapshot_a = (
            await client.get(
                "/analytics/seller-daily", params={"org_id": org_a_id, "date": today}
            )
        ).json()
        snapshot_b = (
            await client.get(
                "/analytics/seller-daily", params={"org_id": org_b_id, "date": today}
            )
        ).json()

        # Seller A's revenue must not include seller B's sale, and vice versa —
        # this is exactly the org_id attribution infer_order_org_id() fixes.
        assert snapshot_a["revenue"]["gross_revenue"] == 50000
        assert snapshot_b["revenue"]["gross_revenue"] == 20000
        assert {p["product_id"] for p in snapshot_a["products"]} == {product_a["id"]}
        assert {p["product_id"] for p in snapshot_b["products"]} == {product_b["id"]}


@pytest.mark.asyncio
async def test_seller_daily_snapshot_includes_untouched_products(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        auth = await _signup_seller(client, "daily-untouched@test.com")
        product = await _create_product(client, auth["access_token"], "안 팔린 상품", 40000, 20)

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        snapshot = (
            await client.get(
                "/analytics/seller-daily",
                params={"org_id": auth["customer"]["organization"]["id"], "date": today},
            )
        ).json()

        row = next(p for p in snapshot["products"] if p["product_id"] == product["id"])
        assert row["views"] == 0
        assert row["units_sold"] == 0
        assert snapshot["highlights"]["least_viewed"]["product_id"] == product["id"]


@pytest.mark.asyncio
async def test_internal_organizations_and_order_org_lookup(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        auth = await _signup_seller(client, "daily-internal@test.com")
        org_id = auth["customer"]["organization"]["id"]
        product = await _create_product(client, auth["access_token"], "내부 조회 상품", 10000, 5)

        variant_id = product["variants"][0]["id"]
        await client.post(
            "/carts/cart_internal/items", json={"variant_id": variant_id, "quantity": 1}
        )
        order = (
            await client.post(
                "/checkout/orders", json={"cart_id": "cart_internal", **CHECKOUT_FIELDS}
            )
        ).json()

        orgs = (await client.get("/internal/organizations")).json()
        assert org_id in {o["id"] for o in orgs}

        lookup = (await client.get(f"/internal/orders/{order['id']}/org")).json()
        assert lookup["org_id"] == org_id


@pytest.mark.asyncio
async def test_platform_daily_traffic_is_not_scoped_to_one_seller(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        # The demo seed data (org_test_seller2) already seeds its own
        # PRODUCT_VIEWED events dated today, so this asserts the delta two
        # more sellers' views add, rather than an exact total or top-10 rank.
        baseline = (
            await client.get("/analytics/platform-daily-traffic", params={"date": today})
        ).json()

        seller_a = await _signup_seller(client, "traffic-a@test.com")
        seller_b = await _signup_seller(client, "traffic-b@test.com")
        product_a = await _create_product(client, seller_a["access_token"], "트래픽 A", 10000, 5)
        product_b = await _create_product(client, seller_b["access_token"], "트래픽 B", 10000, 5)

        for _ in range(5):
            await client.post("/events/product-view", json={"product_id": product_a["id"]})
        await client.post("/events/product-view", json={"product_id": product_b["id"]})

        snapshot = (
            await client.get("/analytics/platform-daily-traffic", params={"date": today})
        ).json()

        # Unlike seller_daily_snapshot, this endpoint sees every seller's
        # products at once — that's the whole point of it being admin-only.
        assert snapshot["total_views"] - baseline["total_views"] == 6


@pytest.mark.asyncio
async def test_seller_market_share_splits_revenue_by_seller(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller_a = await _signup_seller(client, "share-a@test.com")
        seller_b = await _signup_seller(client, "share-b@test.com")
        product_a = await _create_product(client, seller_a["access_token"], "점유율 A", 60000, 10)
        product_b = await _create_product(client, seller_b["access_token"], "점유율 B", 20000, 10)

        totals: dict[str, int] = {}
        for key, product in (("a", product_a), ("b", product_b)):
            variant_id = product["variants"][0]["id"]
            cart_id = f"cart_share_{product['id']}"
            await client.post(
                f"/carts/{cart_id}/items", json={"variant_id": variant_id, "quantity": 1}
            )
            order = (
                await client.post(
                    "/checkout/orders", json={"cart_id": cart_id, **CHECKOUT_FIELDS}
                )
            ).json()
            # Orders under the free-shipping threshold include a shipping
            # fee in their total, so gross revenue isn't just line price.
            totals[key] = order["total"]
            await client.post(
                "/payments/confirm", json={"order_id": order["id"], "amount": order["total"]}
            )

        period = datetime.now(UTC).strftime("%Y-%m")
        snapshot = (
            await client.get("/analytics/seller-market-share", params={"period": period})
        ).json()

        by_org = {row["org_id"]: row for row in snapshot["sellers"]}
        org_a = seller_a["customer"]["organization"]["id"]
        org_b = seller_b["customer"]["organization"]["id"]
        # gross_revenue (the seller's own sales) is org-scoped so it's exact
        # regardless of other sellers' seed revenue. Share is based on
        # *platform* revenue, not GMV: a brand-new signup defaults to the
        # FREE plan (plan_fee=0), so platform_contribution here is exactly
        # the 8% commission on gross_revenue — no plan fee involved.
        assert by_org[org_a]["gross_revenue"] == totals["a"]
        assert by_org[org_b]["gross_revenue"] == totals["b"]
        assert by_org[org_a]["plan"] == "FREE"
        assert by_org[org_a]["commission_revenue"] == round(totals["a"] * 0.08)
        assert by_org[org_a]["plan_fee"] == 0
        assert by_org[org_a]["platform_contribution"] == by_org[org_a]["commission_revenue"]

        total = snapshot["total_platform_revenue"]
        expected_a = round(by_org[org_a]["platform_contribution"] / total * 100, 1)
        expected_b = round(by_org[org_b]["platform_contribution"] / total * 100, 1)
        assert by_org[org_a]["share_pct"] == expected_a
        assert by_org[org_b]["share_pct"] == expected_b


@pytest.mark.asyncio
async def test_a_paid_plan_seller_can_out_contribute_a_bigger_free_seller(commerce_app) -> None:
    """The site's own revenue model: commission + plan fee, not raw GMV.

    A FREE-plan seller with much higher sales can still contribute *less*
    platform revenue than a BUSINESS-plan seller with modest sales — the
    whole reason seller_market_share() must never just rank by gross_revenue.
    """
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        free_seller = await _signup_seller(client, "plan-free@test.com")
        paid_seller = await _signup_seller(client, "plan-paid@test.com")
        # 무료 플랜인데 매출은 훨씬 큼
        big_product = await _create_product(
            client, free_seller["access_token"], "무료 플랜 베스트셀러", 200000, 10
        )
        # 유료 플랜인데 매출은 훨씬 작음
        small_product = await _create_product(
            client, paid_seller["access_token"], "유료 플랜 상품", 10000, 10
        )

        for product in (big_product, small_product):
            variant_id = product["variants"][0]["id"]
            cart_id = f"cart_plan_{product['id']}"
            await client.post(
                f"/carts/{cart_id}/items", json={"variant_id": variant_id, "quantity": 1}
            )
            order = (
                await client.post(
                    "/checkout/orders", json={"cart_id": cart_id, **CHECKOUT_FIELDS}
                )
            ).json()
            await client.post(
                "/payments/confirm", json={"order_id": order["id"], "amount": order["total"]}
            )

        paid_org_id = paid_seller["customer"]["organization"]["id"]
        free_org_id = free_seller["customer"]["organization"]["id"]
        db, _main, _analytics = commerce_app
        with db.transaction() as connection:
            connection.execute(
                "UPDATE organizations SET plan = 'BUSINESS' WHERE id = ?", (paid_org_id,)
            )

        period = datetime.now(UTC).strftime("%Y-%m")
        snapshot = (
            await client.get("/analytics/seller-market-share", params={"period": period})
        ).json()
        by_org = {row["org_id"]: row for row in snapshot["sellers"]}

        assert by_org[free_org_id]["gross_revenue"] > by_org[paid_org_id]["gross_revenue"]
        assert (
            by_org[paid_org_id]["platform_contribution"]
            > by_org[free_org_id]["platform_contribution"]
        )
        assert by_org[paid_org_id]["share_pct"] > by_org[free_org_id]["share_pct"]
