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
            "category_id": "cat_fashion",
            "description": "테스트 상품",
            "price": price,
            "color": "블랙",
            "size": "M",
            "stock": stock,
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
