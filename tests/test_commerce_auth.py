"""Signup/login/seller-activation/Google-auth tests for mock-commerce-api.

See conftest.py's ``commerce_app`` fixture docstring for why this module
loads mock-commerce-api's ``app`` package the way it does.
"""

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


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_signup_and_login_roundtrip(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        signup = await client.post(
            "/auth/signup",
            json={
                "email": "consumer@example.com",
                "password": "correct-horse",
                "name": "박소비",
                "phone": "010-2222-3333",
            },
        )
        assert signup.status_code == 201
        body = signup.json()
        assert body["customer"]["role"] == "CONSUMER"
        assert body["customer"]["organization"] is None
        assert "password_hash" not in body["customer"]

        login = await client.post(
            "/auth/login", json={"email": "consumer@example.com", "password": "correct-horse"}
        )
        assert login.status_code == 200
        assert login.json()["customer"]["id"] == body["customer"]["id"]


@pytest.mark.asyncio
async def test_login_wrong_password_is_rejected(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        await client.post(
            "/auth/signup",
            json={
                "email": "consumer2@example.com",
                "password": "correct-horse",
                "name": "박소비",
                "phone": "010-2222-3333",
            },
        )
        response = await client.post(
            "/auth/login", json={"email": "consumer2@example.com", "password": "wrong-password"}
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_signup_duplicate_email_is_rejected(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        payload = {
            "email": "dupe@example.com",
            "password": "correct-horse",
            "name": "박소비",
            "phone": "010-2222-3333",
        }
        first = await client.post("/auth/signup", json=payload)
        second = await client.post("/auth/signup", json=payload)
        assert first.status_code == 201
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_signup_as_seller_creates_organization(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        response = await client.post(
            "/auth/signup",
            json={
                "email": "seller@example.com",
                "password": "correct-horse",
                "name": "김판매",
                "phone": "010-4444-5555",
                "as_seller": True,
                "shop_name": "김판매의 옷장",
                "shop_category": "패션",
            },
        )
        assert response.status_code == 201
        customer = response.json()["customer"]
        assert customer["role"] == "SELLER"
        assert customer["organization"]["name"] == "김판매의 옷장"
        assert customer["organization"]["category"] == "패션"
        assert customer["organization"]["commission_rate"] == pytest.approx(0.08)


@pytest.mark.asyncio
async def test_signup_as_seller_without_shop_info_is_rejected(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        response = await client.post(
            "/auth/signup",
            json={
                "email": "seller2@example.com",
                "password": "correct-horse",
                "name": "김판매",
                "phone": "010-4444-5555",
                "as_seller": True,
            },
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_customers_me_requires_auth(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        response = await client.get("/customers/me")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_seller_activation_flow(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        signup = await client.post(
            "/auth/signup",
            json={
                "email": "activator@example.com",
                "password": "correct-horse",
                "name": "이전환",
                "phone": "010-6666-7777",
            },
        )
        token = signup.json()["access_token"]

        before = await client.get("/customers/me", headers=_auth_header(token))
        assert before.json()["role"] == "CONSUMER"

        activated = await client.post(
            "/sellers/activate",
            json={"shop_name": "이전환 스토어", "shop_category": "잡화"},
            headers=_auth_header(token),
        )
        assert activated.status_code == 201
        assert activated.json()["role"] == "SELLER"

        after = await client.get("/customers/me", headers=_auth_header(token))
        assert after.json()["role"] == "SELLER"
        assert after.json()["organization"]["name"] == "이전환 스토어"

        again = await client.post(
            "/sellers/activate",
            json={"shop_name": "다른 이름", "shop_category": "잡화"},
            headers=_auth_header(token),
        )
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_checkout_attributes_order_to_authenticated_customer(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        signup_a = await client.post(
            "/auth/signup",
            json={
                "email": "shopper-a@example.com",
                "password": "correct-horse",
                "name": "쇼퍼A",
                "phone": "010-1111-1111",
            },
        )
        token_a = signup_a.json()["access_token"]
        customer_a_id = signup_a.json()["customer"]["id"]

        signup_b = await client.post(
            "/auth/signup",
            json={
                "email": "shopper-b@example.com",
                "password": "correct-horse",
                "name": "쇼퍼B",
                "phone": "010-2222-2222",
            },
        )
        token_b = signup_b.json()["access_token"]

        cart_id = "cart_auth_test"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        order_response = await client.post(
            "/checkout/orders",
            json={"cart_id": cart_id, **CHECKOUT_FIELDS},
            headers=_auth_header(token_a),
        )
        assert order_response.status_code == 201
        assert order_response.json()["customer_id"] == customer_a_id

        my_orders_a = await client.get("/customers/me/orders", headers=_auth_header(token_a))
        assert any(o["id"] == order_response.json()["id"] for o in my_orders_a.json())

        my_orders_b = await client.get("/customers/me/orders", headers=_auth_header(token_b))
        assert my_orders_b.json() == []


@pytest.mark.asyncio
async def test_checkout_without_auth_is_an_unattributed_guest_order(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        cart_id = "cart_guest_test"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_002_iv", "quantity": 1}
        )
        order_response = await client.post(
            "/checkout/orders", json={"cart_id": cart_id, **CHECKOUT_FIELDS}
        )
        assert order_response.status_code == 201
        assert order_response.json()["customer_id"] is None


@pytest.mark.asyncio
async def test_google_auth_creates_new_consumer(commerce_app, monkeypatch) -> None:
    _db, main, analytics = commerce_app
    del analytics
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "aud": "test-client-id",
                "email": "googler@example.com",
                "email_verified": "true",
                "name": "구글러",
            }

    import app.auth as auth_module

    monkeypatch.setattr(auth_module.httpx, "get", lambda *a, **k: FakeResponse())

    async with await _client(main) as client:
        response = await client.post("/auth/google", json={"id_token": "fake-google-credential"})
        assert response.status_code == 200
        customer = response.json()["customer"]
        assert customer["email"] == "googler@example.com"
        assert customer["role"] == "CONSUMER"

        # A second call with the same email logs into the same account rather
        # than creating a duplicate.
        again = await client.post("/auth/google", json={"id_token": "fake-google-credential"})
        assert again.json()["customer"]["id"] == customer["id"]


@pytest.mark.asyncio
async def test_google_auth_without_client_id_configured(commerce_app, monkeypatch) -> None:
    _db, main, _analytics = commerce_app
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    async with await _client(main) as client:
        response = await client.post("/auth/google", json={"id_token": "whatever-token"})
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_google_auth_rejects_audience_mismatch(commerce_app, monkeypatch) -> None:
    _db, main, _analytics = commerce_app
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "aud": "someone-elses-client-id",
                "email": "victim@example.com",
                "email_verified": "true",
            }

    import app.auth as auth_module

    monkeypatch.setattr(auth_module.httpx, "get", lambda *a, **k: FakeResponse())

    async with await _client(main) as client:
        response = await client.post("/auth/google", json={"id_token": "fake-google-credential"})
        assert response.status_code == 401
