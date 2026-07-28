"""Seller product management and admin organization moderation tests.

See conftest.py's ``commerce_app`` fixture docstring for why this module
loads mock-commerce-api's ``app`` package the way it does.
"""

import pytest
from httpx import ASGITransport, AsyncClient


async def _client(main):
    transport = ASGITransport(app=main.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup_seller(client, email: str) -> dict[str, object]:
    response = await client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "correct-horse",
            "name": "김판매",
            "phone": "010-5555-6666",
            "as_seller": True,
            "shop_name": "새 판매자 상점",
            "shop_category": "패션",
        },
    )
    assert response.status_code == 201
    return response.json()


NEW_PRODUCT = {
    "name": "New Seller Jacket",
    "category_id": "cat_outer_jacket",
    "description": "새로 등록한 판매자 상품입니다.",
    "material": "폴리에스터 100%",
    "care": "드라이클리닝",
    "price": 89000,
    "variants": [{"color": "블랙", "size": "L", "stock": 5}],
}


@pytest.mark.asyncio
async def test_consumer_cannot_manage_products(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        signup = await client.post(
            "/auth/signup",
            json={
                "email": "plain-consumer@example.com",
                "password": "correct-horse",
                "name": "박소비",
                "phone": "010-7777-8888",
            },
        )
        token = signup.json()["access_token"]
        response = await client.post(
            "/sellers/me/products", json=NEW_PRODUCT, headers=_auth_header(token)
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_seller_can_create_and_list_own_products(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller = await _signup_seller(client, "new-seller@example.com")
        token = seller["access_token"]

        created = await client.post(
            "/sellers/me/products", json=NEW_PRODUCT, headers=_auth_header(token)
        )
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "New Seller Jacket"
        assert body["org_id"] == seller["customer"]["organization"]["id"]
        assert len(body["variants"]) == 1
        assert body["variants"][0]["stock"] == 5

        listed = await client.get("/sellers/me/products", headers=_auth_header(token))
        assert listed.status_code == 200
        assert [p["id"] for p in listed.json()] == [body["id"]]

        # And it shows up in the public catalog like any other product.
        public = await client.get("/products", params={"q": "New Seller Jacket"})
        assert any(p["id"] == body["id"] for p in public.json())


@pytest.mark.asyncio
async def test_seller_cannot_manage_another_sellers_product(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller_a = await _signup_seller(client, "seller-a@example.com")
        seller_b = await _signup_seller(client, "seller-b@example.com")

        created = await client.post(
            "/sellers/me/products", json=NEW_PRODUCT, headers=_auth_header(seller_a["access_token"])
        )
        product = created.json()
        variant_id = product["variants"][0]["id"]

        response = await client.patch(
            f"/sellers/me/products/{product['id']}/variants/{variant_id}",
            json={"stock": 100},
            headers=_auth_header(seller_b["access_token"]),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_seller_can_update_own_variant_stock_and_price(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller = await _signup_seller(client, "stock-seller@example.com")
        token = seller["access_token"]
        created = (
            await client.post("/sellers/me/products", json=NEW_PRODUCT, headers=_auth_header(token))
        ).json()
        variant_id = created["variants"][0]["id"]

        updated = await client.patch(
            f"/sellers/me/products/{created['id']}/variants/{variant_id}",
            json={"stock": 20, "price": 79000},
            headers=_auth_header(token),
        )
        assert updated.status_code == 200
        variant = updated.json()["variants"][0]
        assert variant["stock"] == 20
        assert variant["price"] == 79000


@pytest.mark.asyncio
async def test_non_admin_cannot_list_organizations(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller = await _signup_seller(client, "not-admin@example.com")
        response = await client.get(
            "/admin/organizations", headers=_auth_header(seller["access_token"])
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_suspend_and_reactivate_a_seller(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        seller = await _signup_seller(client, "suspend-me@example.com")
        seller_token = seller["access_token"]
        org_id = seller["customer"]["organization"]["id"]
        product = (
            await client.post(
                "/sellers/me/products", json=NEW_PRODUCT, headers=_auth_header(seller_token)
            )
        ).json()

        admin_login = await client.post(
            "/auth/login", json={"email": "admin@test.com", "password": "test1234"}
        )
        assert admin_login.status_code == 200
        assert admin_login.json()["customer"]["role"] == "ADMIN"
        admin_token = admin_login.json()["access_token"]

        orgs = await client.get("/admin/organizations", headers=_auth_header(admin_token))
        assert orgs.status_code == 200
        assert any(o["id"] == org_id for o in orgs.json())

        before = await client.get("/products", params={"q": "New Seller Jacket"})
        assert any(p["id"] == product["id"] for p in before.json())

        suspend = await client.patch(
            f"/admin/organizations/{org_id}",
            json={"status": "SUSPENDED"},
            headers=_auth_header(admin_token),
        )
        assert suspend.status_code == 200
        assert suspend.json()["status"] == "SUSPENDED"

        # A suspended seller's listings disappear from the public catalog...
        hidden = await client.get("/products", params={"q": "New Seller Jacket"})
        assert not any(p["id"] == product["id"] for p in hidden.json())

        reactivate = await client.patch(
            f"/admin/organizations/{org_id}",
            json={"status": "ACTIVE"},
            headers=_auth_header(admin_token),
        )
        assert reactivate.status_code == 200

        # ...and come back once reactivated.
        restored = await client.get("/products", params={"q": "New Seller Jacket"})
        assert any(p["id"] == product["id"] for p in restored.json())


@pytest.mark.asyncio
async def test_seed_test_accounts_log_in_with_expected_roles(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        consumer = await client.post(
            "/auth/login", json={"email": "consumer@test.com", "password": "test1234"}
        )
        assert consumer.status_code == 200
        assert consumer.json()["customer"]["role"] == "CONSUMER"

        seller = await client.post(
            "/auth/login", json={"email": "seller@test.com", "password": "test1234"}
        )
        assert seller.status_code == 200
        assert seller.json()["customer"]["role"] == "SELLER"
        assert seller.json()["customer"]["organization"]["name"] == "테스트 스토어"

        seller_products = await client.get(
            "/sellers/me/products", headers=_auth_header(seller.json()["access_token"])
        )
        assert len(seller_products.json()) == 2

        admin = await client.post(
            "/auth/login", json={"email": "admin@test.com", "password": "test1234"}
        )
        assert admin.status_code == 200
        assert admin.json()["customer"]["role"] == "ADMIN"
